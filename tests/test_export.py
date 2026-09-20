"""Tests for expra_engine.export — game export pipeline.

All tests use injected fakes; no network, no disk I/O beyond temp dirs.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from expra_engine.export.events import ExportPhase, ExportProgressEvent
from expra_engine.export.exporter import ExportError, GameExporter
from expra_engine.export.manifest import (
    AssetManifest,
    BuildManifest,
    _should_exclude,
)
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch
from expra_engine.export.verify import ExportVerificationError, verify_export

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path, entry: str = "game/__main__.py") -> Path:
    """Create a minimal project tree and return project_dir."""
    project = tmp / "myproject"
    entry_path = project / entry
    entry_path.parent.mkdir(parents=True)
    entry_path.write_text("# main\n")
    return project


def _valid_plan(project: Path, output: Path, **overrides: object) -> ExportPlan:
    defaults: dict[str, object] = {
        "project_dir": project,
        "entry_point": "game/__main__.py",
        "output_dir": output,
        "target": ExportTarget.LINUX,
        "game_name": "My Game",
        "game_version": "1.0.0",
        "python_version": "3.12.4",
    }
    defaults.update(overrides)
    return ExportPlan(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ExportPlan validation
# ---------------------------------------------------------------------------


class ExportPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = _make_project(self.tmp)
        self.output = self.tmp / "out"
        self.output.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_plan_constructs(self) -> None:
        plan = _valid_plan(self.project, self.output)
        self.assertEqual(plan.game_name, "My Game")
        self.assertEqual(plan.target, ExportTarget.LINUX)
        self.assertEqual(plan.arch, PythonArch.AMD64)

    def test_missing_project_dir_raises(self) -> None:
        with self.assertRaises(ValueError, msg="project_dir does not exist"):
            _valid_plan(self.tmp / "nonexistent", self.output)

    def test_missing_entry_point_raises(self) -> None:
        with self.assertRaises(ValueError, msg="entry_point not found"):
            _valid_plan(self.project, self.output, entry_point="game/missing.py")

    def test_invalid_game_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            _valid_plan(self.project, self.output, game_name="!!bad")

    def test_invalid_game_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            _valid_plan(self.project, self.output, game_version="not_semver")

    def test_invalid_python_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            _valid_plan(self.project, self.output, python_version="3.12")

    def test_relative_output_dir_raises(self) -> None:
        with self.assertRaises(ValueError):
            _valid_plan(self.project, Path("relative/path"))

    def test_game_name_with_spaces_ok(self) -> None:
        plan = _valid_plan(self.project, self.output, game_name="Super Shooter")
        self.assertEqual(plan.game_name, "Super Shooter")

    def test_windows_target(self) -> None:
        plan = _valid_plan(self.project, self.output, target=ExportTarget.WINDOWS)
        self.assertEqual(plan.target, ExportTarget.WINDOWS)

    def test_exclude_patterns_frozenset(self) -> None:
        plan = _valid_plan(self.project, self.output, exclude_patterns=frozenset({"secrets.txt"}))
        self.assertIn("secrets.txt", plan.exclude_patterns)


# ---------------------------------------------------------------------------
# AssetManifest
# ---------------------------------------------------------------------------


class AssetManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str, content: str = "x") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_collect_includes_regular_files(self) -> None:
        self._write("assets/sprite.png")
        self._write("game/__main__.py")
        manifest = AssetManifest.collect(self.root)
        paths = {e.path for e in manifest.entries}
        self.assertIn("assets/sprite.png", paths)
        self.assertIn("game/__main__.py", paths)

    def test_collect_excludes_pycache(self) -> None:
        self._write("game/__pycache__/foo.pyc")
        manifest = AssetManifest.collect(self.root)
        self.assertFalse(any("__pycache__" in e.path for e in manifest.entries))

    def test_collect_excludes_psd(self) -> None:
        self._write("art/sprite.psd")
        manifest = AssetManifest.collect(self.root)
        self.assertFalse(any(e.path.endswith(".psd") for e in manifest.entries))

    def test_collect_exclude_source_when_false(self) -> None:
        self._write("game/logic.py")
        self._write("assets/tile.png")
        manifest = AssetManifest.collect(self.root, include_source=False)
        paths = {e.path for e in manifest.entries}
        self.assertNotIn("game/logic.py", paths)
        self.assertIn("assets/tile.png", paths)

    def test_collect_extra_exclude_patterns(self) -> None:
        self._write("game/secrets.txt")
        self._write("game/public.txt")
        manifest = AssetManifest.collect(
            self.root, extra_exclude_patterns=frozenset({"game/secrets.txt"})
        )
        paths = {e.path for e in manifest.entries}
        self.assertNotIn("game/secrets.txt", paths)
        self.assertIn("game/public.txt", paths)

    def test_collect_hashes_present(self) -> None:
        self._write("data.txt", "hello")
        manifest = AssetManifest.collect(self.root)
        self.assertTrue(all(len(e.sha256) == 64 for e in manifest.entries))

    def test_json_round_trip(self) -> None:
        self._write("game/a.py")
        original = AssetManifest.collect(self.root)
        restored = AssetManifest.from_json(original.to_json())
        self.assertEqual(len(original.entries), len(restored.entries))
        self.assertEqual(original.entries[0].path, restored.entries[0].path)

    def test_entries_sorted_by_path(self) -> None:
        self._write("z.txt")
        self._write("a.txt")
        manifest = AssetManifest.collect(self.root)
        paths = [e.path for e in manifest.entries]
        self.assertEqual(paths, sorted(paths))

    def test_should_exclude_git_dir(self) -> None:
        rel = Path(".git") / "config"
        self.assertTrue(_should_exclude(rel, frozenset(), include_source=True))

    def test_should_exclude_blend_file(self) -> None:
        rel = Path("art") / "model.blend"
        self.assertTrue(_should_exclude(rel, frozenset(), include_source=True))

    def test_should_not_exclude_png(self) -> None:
        rel = Path("assets") / "sprite.png"
        self.assertFalse(_should_exclude(rel, frozenset(), include_source=True))


# ---------------------------------------------------------------------------
# BuildManifest
# ---------------------------------------------------------------------------


class BuildManifestTests(unittest.TestCase):
    def _make(self, **overrides: object) -> BuildManifest:
        defaults: dict[str, object] = {
            "game_name": "TestGame",
            "game_version": "0.1.0",
            "engine_version": "1.2.3",
            "target": "linux",
            "python_version": "3.12.4",
            "arch": "amd64",
            "compile_bytecode": True,
            "entry_point": "game/__main__.py",
            "build_timestamp": "2026-01-01T00:00:00+00:00",
            "runtime_profile": "none",
        }
        defaults.update(overrides)
        return BuildManifest(**defaults)  # type: ignore[arg-type]

    def test_to_json_contains_all_keys(self) -> None:
        m = self._make()
        data = json.loads(m.to_json())
        self.assertIn("game_name", data)
        self.assertIn("build_timestamp", data)
        self.assertEqual(data["target"], "linux")

    def test_json_round_trip(self) -> None:
        original = self._make()
        restored = BuildManifest.from_json(original.to_json())
        self.assertEqual(original.game_name, restored.game_name)
        self.assertEqual(original.compile_bytecode, restored.compile_bytecode)


# ---------------------------------------------------------------------------
# verify_export
# ---------------------------------------------------------------------------


class VerifyExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.build_dir = Path(self._tmp.name) / "build"
        self.build_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_valid_build(self) -> None:
        manifest = {
            "game_name": "TestGame",
            "game_version": "0.1.0",
            "engine_version": "0.1.8.0",
            "target": "linux",
            "python_version": "3.12.4",
            "arch": "amd64",
            "compile_bytecode": True,
            "entry_point": "game/__main__.py",
            "build_timestamp": "2026-01-01T00:00:00+00:00",
            "runtime_profile": "none",
        }
        (self.build_dir / "build_manifest.json").write_text(json.dumps(manifest))
        (self.build_dir / "asset_manifest.json").write_text(json.dumps({"entries": []}))

    def test_valid_build_passes(self) -> None:
        self._write_valid_build()
        verify_export(self.build_dir)  # must not raise

    def test_missing_build_dir_raises(self) -> None:
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir / "nonexistent")

    def test_missing_build_manifest_raises(self) -> None:
        (self.build_dir / "asset_manifest.json").write_text('{"entries":[]}')
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir)

    def test_missing_asset_manifest_raises(self) -> None:
        self._write_valid_build()
        (self.build_dir / "asset_manifest.json").unlink()
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir)

    def test_invalid_json_in_manifest_raises(self) -> None:
        (self.build_dir / "build_manifest.json").write_text("not json {{{")
        (self.build_dir / "asset_manifest.json").write_text('{"entries":[]}')
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir)

    def test_missing_required_key_raises(self) -> None:
        self._write_valid_build()
        data = json.loads((self.build_dir / "build_manifest.json").read_text())
        del data["game_name"]
        (self.build_dir / "build_manifest.json").write_text(json.dumps(data))
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir)

    def test_asset_manifest_missing_entries_key_raises(self) -> None:
        self._write_valid_build()
        (self.build_dir / "asset_manifest.json").write_text('{"wrong_key": []}')
        with self.assertRaises(ExportVerificationError):
            verify_export(self.build_dir)


# ---------------------------------------------------------------------------
# ExportProgressEvent
# ---------------------------------------------------------------------------


class ExportProgressEventTests(unittest.TestCase):
    def test_event_fields(self) -> None:
        evt = ExportProgressEvent(phase=ExportPhase.COLLECTING_ASSETS, message="msg", percent=42)
        self.assertEqual(evt.phase, ExportPhase.COLLECTING_ASSETS)
        self.assertEqual(evt.message, "msg")
        self.assertEqual(evt.percent, 42)

    def test_all_phases_are_strings(self) -> None:
        for phase in ExportPhase:
            self.assertIsInstance(phase.value, str)


# ---------------------------------------------------------------------------
# GameExporter (stub packager — no real network or disk I/O)
# ---------------------------------------------------------------------------


class _StubPackager:
    """Packager that writes minimal required files without network I/O."""

    def install_runtime(
        self,
        python_version: str,
        arch: str,
        dest: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: object,
        downloader: object = None,
    ) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    def install_packages(
        self,
        packages: list[str],
        python_version: str,
        arch: str,
        site_packages: Path,
        *,
        cache_dir: Path,
        cancel: threading.Event,
        progress: object,
        downloader: object = None,
    ) -> None:
        site_packages.mkdir(parents=True, exist_ok=True)

    def make_launcher(
        self,
        build_dir: Path,
        game_name: str,
        entry_point: str,
        source_subdir: str,
        *,
        is_pyc: bool,
        debug: bool,
    ) -> None:
        suffix = "_debug" if debug else ""
        (build_dir / f"launch{suffix}.sh").write_text("#!/bin/sh\n")


class GameExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = _make_project(self.tmp)
        self.output = self.tmp / "out"
        self.output.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, **plan_overrides: object) -> tuple[Path, list[ExportProgressEvent]]:
        plan = _valid_plan(self.project, self.output, **plan_overrides)
        events: list[ExportProgressEvent] = []
        exporter = GameExporter(packager=_StubPackager())  # type: ignore[arg-type]
        cancel = threading.Event()
        result = exporter.export(plan, cancel=cancel, progress=events.append)
        return result, events

    def test_export_returns_final_dir(self) -> None:
        final_dir, _ = self._run()
        self.assertTrue(final_dir.is_dir())

    def test_export_creates_build_manifest(self) -> None:
        final_dir, _ = self._run()
        manifest_path = final_dir / "build_manifest.json"
        self.assertTrue(manifest_path.exists())
        data = json.loads(manifest_path.read_text())
        self.assertEqual(data["game_name"], "My Game")
        self.assertEqual(data["target"], "linux")

    def test_export_creates_asset_manifest(self) -> None:
        final_dir, _ = self._run()
        manifest_path = final_dir / "asset_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertIsInstance(manifest["entries"], list)

    def test_export_emits_progress_events(self) -> None:
        _, events = self._run()
        phases = [e.phase for e in events]
        self.assertIn(ExportPhase.PLANNING, phases)
        self.assertIn(ExportPhase.DONE, phases)

    def test_done_event_has_100_percent(self) -> None:
        _, events = self._run()
        done_events = [e for e in events if e.phase == ExportPhase.DONE]
        self.assertTrue(done_events)
        self.assertEqual(done_events[-1].percent, 100)

    def test_cancel_before_start_raises(self) -> None:
        plan = _valid_plan(self.project, self.output)
        exporter = GameExporter(packager=_StubPackager())  # type: ignore[arg-type]
        cancel = threading.Event()
        cancel.set()  # cancel immediately

        with self.assertRaises(ExportError):
            exporter.export(plan, cancel=cancel)

    def test_export_game_name_slugified_in_dir(self) -> None:
        final_dir, _ = self._run(game_name="Super Shooter")
        self.assertIn("Super_Shooter", final_dir.name)

    def test_no_progress_callback_ok(self) -> None:
        plan = _valid_plan(self.project, self.output)
        exporter = GameExporter(packager=_StubPackager())  # type: ignore[arg-type]
        cancel = threading.Event()
        result = exporter.export(plan, cancel=cancel)
        self.assertTrue(result.is_dir())


if __name__ == "__main__":
    unittest.main()
