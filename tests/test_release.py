"""Focused tests for the expra-engine release/build helpers."""

import hashlib
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from expra_engine import _release


def _make_package(root: Path, version: str) -> None:
    pkg = root / "src" / "expra_engine"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from expra_engine._version import __version__\n")
    (pkg / "_version.py").write_text(f'__version__ = "{version}"\n')
    (pkg / "main.py").write_text("def main():\n    return 0\n")
    (pkg / "py.typed").write_text("")
    for subpackage in ("core", "editor", "runtime", "design"):
        subdir = pkg / subpackage
        subdir.mkdir()
        (subdir / "__init__.py").write_text("")
    for relative in (
        "editor/app.py",
        "editor/delivery.py",
        "editor/instance_lock.py",
        "editor/persistence.py",
        "editor/preferences.py",
        "runtime/clock.py",
        "runtime/event_queue.py",
        "runtime/events.py",
        "runtime/system.py",
        "design/tokens.py",
    ):
        (pkg / relative).write_text("")


def _wheel_from_package(root: Path, version: str) -> Path:
    """Zip the exact source bytes into a wheel so manifests compare equal."""

    wheel = root / "dist" / f"expra_engine-{version}-py3-none-any.whl"
    wheel.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in sorted((root / "src" / "expra_engine").rglob("*")):
            if path.is_file():
                relative = path.relative_to(root / "src" / "expra_engine").as_posix()
                archive.writestr(f"expra_engine/{relative}", path.read_bytes())
        archive.writestr(
            f"expra_engine-{version}.dist-info/entry_points.txt",
            "[console_scripts]\nexpra-editor = expra_engine.main:main\n",
        )
        archive.writestr(
            f"expra_engine-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: expra-engine\nVersion: {version}\n",
        )
    return wheel


class VersionHelpersTests(unittest.TestCase):
    def test_parse_and_format_round_trip(self) -> None:
        self.assertEqual(_release._format_version(_release._parse_version("1.2.3.4")), "1.2.3.4")

    def test_parse_rejects_non_four_segment_versions(self) -> None:
        with self.assertRaises(ValueError):
            _release._parse_version("1.0.0")

    def test_bump_carries_into_earlier_segments(self) -> None:
        self.assertEqual(
            _release._format_version(_release._bump_segment((1, 2, 3, 4), 3)), "1.2.3.5"
        )
        self.assertEqual(
            _release._format_version(_release._bump_segment((1, 2, 3, 9), 3)), "1.2.4.0"
        )
        self.assertEqual(
            _release._format_version(_release._bump_segment((1, 2, 9, 9), 2)), "1.3.0.9"
        )
        self.assertEqual(
            _release._format_version(_release._bump_segment((1, 9, 9, 9), 1)), "2.0.9.9"
        )

    def test_next_version_levels(self) -> None:
        self.assertEqual(_release._next_version("1.2.3.4", "none"), "1.2.3.4")
        self.assertEqual(_release._next_version("1.2.3.4", "patch"), "1.2.3.5")
        self.assertEqual(_release._next_version("1.2.3.4", "feature"), "1.2.4.0")
        self.assertEqual(_release._next_version("1.2.3.4", "minor"), "1.3.0.0")

    def test_pick_base_version_prefers_newer(self) -> None:
        self.assertEqual(_release._pick_base_version("1.0.0.0", None), "1.0.0.0")
        self.assertEqual(_release._pick_base_version("1.0.0.0", "1.2.0.0"), "1.2.0.0")
        self.assertEqual(_release._pick_base_version("1.5.0.0", "1.2.0.0"), "1.5.0.0")


class ManifestDiffTests(unittest.TestCase):
    def test_diff_categorises_added_removed_changed(self) -> None:
        diff = _release.diff_manifests(
            {"a": "1", "b": "1", "c": "1"},
            {"b": "2", "c": "1", "d": "1"},
        )
        self.assertEqual(diff.added, ("d",))
        self.assertEqual(diff.removed, ("a",))
        self.assertEqual(diff.changed, ("b",))

    def test_classify_bump_levels(self) -> None:
        no_change = _release.DiffSummary((), (), ())
        self.assertEqual(_release.classify_bump(no_change), "none")

        minor = _release.DiffSummary(("expra_engine/core/engine.py",), (), ())
        self.assertEqual(_release.classify_bump(minor), "minor")

        feature_add = _release.DiffSummary(("expra_engine/runtime/event_queue.py",), (), ())
        self.assertEqual(_release.classify_bump(feature_add), "feature")

        feature_change = _release.DiffSummary(
            (), (), ("expra_engine/coordinators/app_coordinator.py",)
        )
        self.assertEqual(_release.classify_bump(feature_change), "feature")

        design_change = _release.DiffSummary((), (), ("expra_engine/design/tokens.py",))
        self.assertEqual(_release.classify_bump(design_change), "feature")

        editor_panel_change = _release.DiffSummary((), (), ("expra_engine/ui/inspector.py",))
        self.assertEqual(_release.classify_bump(editor_panel_change), "feature")

        patch_change = _release.DiffSummary((), (), ("expra_engine/core/utils.py",))
        self.assertEqual(_release.classify_bump(patch_change), "patch")

    def test_classify_bump_override(self) -> None:
        diff = _release.DiffSummary((), (), ("expra_engine/core/utils.py",))
        self.assertEqual(_release.classify_bump(diff, override="minor"), "minor")
        with self.assertRaises(ValueError):
            _release.classify_bump(diff, override="bogus")


class VersionFileTests(unittest.TestCase):
    def test_editor_texture_dependency_is_installed_with_package(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn("pygame>=2.6", pyproject["project"]["dependencies"])
        self.assertNotIn("runtime-pygame", pyproject["project"].get("optional-dependencies", {}))

    def test_project_metadata_uses_canonical_version_module(self) -> None:
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('version = { attr = "expra_engine._version.__version__" }', pyproject)

    def test_read_and_write_version_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            version_path = package / "src" / "expra_engine"
            version_path.mkdir(parents=True)
            (version_path / "_version.py").write_text('__version__ = "1.0.0.0"\n', encoding="utf-8")
            self.assertEqual(_release.read_current_version(package), "1.0.0.0")
            _release.write_current_version(package, "1.1.0.0")
            self.assertEqual(_release.read_current_version(package), "1.1.0.0")


class WheelManifestTests(unittest.TestCase):
    def test_version_change_does_not_count_as_content_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.2.3.4")
            wheel = _wheel_from_package(root, "1.2.3.4")
            wheel_manifest = _release._read_manifest_from_wheel(wheel)

            _release.write_current_version(root, "1.2.3.5")
            source_manifest = _release._collect_package_inputs(root)

            diff = _release.diff_manifests(wheel_manifest, source_manifest)
            self.assertFalse(diff.has_changes, diff)

    def test_real_content_change_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            wheel_manifest = _release._read_manifest_from_wheel(wheel)

            (root / "src" / "expra_engine" / "__init__.py").write_text("# changed\n")
            source_manifest = _release._collect_package_inputs(root)

            diff = _release.diff_manifests(wheel_manifest, source_manifest)
            self.assertIn("expra_engine/__init__.py", diff.changed)

    def test_package_data_is_a_build_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            (root / "src" / "expra_engine" / "runtime.dat").write_bytes(b"runtime")
            wheel = _wheel_from_package(root, "1.0.0.0")
            manifest = _release._read_manifest_from_wheel(wheel)
            self.assertIn("expra_engine/runtime.dat", manifest)

    def test_prepare_build_bumps_once_then_stays_put_with_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")

            first = _release.prepare_build(root)
            version_after_first = _release.read_current_version(root)
            self.assertEqual(version_after_first, first)

            _wheel_from_package(root, version_after_first)
            second = _release.prepare_build(root)
            self.assertEqual(second, version_after_first)
            self.assertEqual(_release.read_current_version(root), version_after_first)

    def test_rewrite_sha256sums_contains_only_newest_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            _wheel_from_package(root, "1.0.0.0")
            newer = _wheel_from_package(root, "1.1.0.0")
            _release.rewrite_sha256sums(root / "dist")
            lines = (root / "dist" / "SHA256SUMS").read_text().splitlines()

            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].endswith("expra_engine-1.1.0.0-py3-none-any.whl"), lines[0])
            expected = hashlib.sha256(newer.read_bytes()).hexdigest()
            self.assertEqual(lines[0].split()[0], expected)


class WheelVerifyTests(unittest.TestCase):
    def test_verify_accepts_valid_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            _release.verify_wheel(wheel)  # must not raise

    def test_verify_rejects_forbidden_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("secrets/.env", "TOKEN=x")
            with self.assertRaises(ValueError):
                _release.verify_wheel(wheel)

    def test_verify_rejects_missing_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            rebuild = root / "dist" / "stripped.whl"
            with zipfile.ZipFile(wheel) as source:
                keep = [name for name in source.namelist() if name != "expra_engine/__init__.py"]
                with zipfile.ZipFile(rebuild, "w") as archive:
                    for name in keep:
                        archive.writestr(name, source.read(name))
            with self.assertRaises(ValueError):
                _release.verify_wheel(rebuild)

    def test_verify_rejects_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            mismatched = root / "dist" / "expra_engine-1.0.0.1-py3-none-any.whl"
            wheel.rename(mismatched)
            with self.assertRaises(ValueError):
                _release.verify_wheel(mismatched)

    def test_verify_rejects_wrong_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_package(root, "1.0.0.0")
            wheel = _wheel_from_package(root, "1.0.0.0")
            rewritten = root / "dist" / "wrong-entry.whl"
            with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(rewritten, "w") as target:
                for name in source.namelist():
                    if name.endswith(".dist-info/entry_points.txt"):
                        target.writestr(
                            name,
                            "[console_scripts]\nwrong = expra_engine.main:main\n",
                        )
                    else:
                        target.writestr(name, source.read(name))
            wheel.unlink()
            rewritten.rename(wheel)
            with self.assertRaises(ValueError):
                _release.verify_wheel(wheel)


if __name__ == "__main__":
    unittest.main()
