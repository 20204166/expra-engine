"""Tests for GameExporter with a mock packager (no network, no real Python download)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from expra_engine._version import __version__
from expra_engine.export.events import ExportPhase, ExportProgressEvent
from expra_engine.export.exporter import (
    ExportError,
    GameExporter,
    _engine_version,
    _merge_manifests,
)
from expra_engine.export.manifest import AssetEntry, AssetManifest
from expra_engine.export.packager import TargetPackager
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch, RuntimeProfile
from expra_engine.export.verify import verify_export
from expra_engine.filesystem import DirectoryMount, MountSpec, ResourceResolver, ResourceService


class _NoopPackager(TargetPackager):
    """Mock packager: does nothing except write a placeholder python.exe."""

    def __init__(self, target: ExportTarget) -> None:
        self._target = target
        self.packages: list[str] = []

    def install_runtime(
        self, python_version, arch, dest, *, cache_dir, cancel, progress, downloader=None
    ):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "python.exe").write_bytes(b"stub")

    def install_packages(
        self, packages, python_version, arch, site_packages, *, cache_dir, cancel, progress
    ):
        self.packages = packages
        site_packages.mkdir(parents=True, exist_ok=True)

    def make_launcher(self, build_dir, game_name, entry_point, source_subdir, *, is_pyc, debug):
        suffix = "_debug" if debug else ""
        ext = ".bat" if self._target == ExportTarget.WINDOWS else ".sh"
        (build_dir / f"{game_name.replace(' ', '_')}{suffix}{ext}").write_text("stub")


def _make_project(tmp: Path) -> tuple[Path, Path]:
    project = tmp / "my_game"
    project.mkdir()
    (project / "__main__.py").write_text("print('hello')")
    (project / "assets").mkdir()
    (project / "assets" / "sprite.png").write_bytes(b"\x89PNG")
    output = tmp / "builds"
    output.mkdir()
    return project, output

class TestGameExporter(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._project, self._output = _make_project(self._tmp)

    def _plan(self, **overrides: object) -> ExportPlan:
        defaults: dict = {
            "project_dir": self._project,
            "entry_point": "__main__.py",
            "output_dir": self._output,
            "target": ExportTarget.WINDOWS,
            "game_name": "Test Game",
            "game_version": "1.0.0",
            "python_version": "3.12.4",
            "arch": PythonArch.AMD64,
            "compile_bytecode": False,
        }
        defaults.update(overrides)
        return ExportPlan(**defaults)  # type: ignore[arg-type]

    def _export(
        self,
        plan: ExportPlan,
        *,
        progress: Callable[[ExportProgressEvent], None] | None = None,
        packager: TargetPackager | None = None,
    ) -> Path:
        cancel = threading.Event()
        exporter = GameExporter(
            packager=packager if packager is not None else _NoopPackager(plan.target)
        )
        return exporter.export(plan, cancel=cancel, progress=progress)

    def test_export_creates_output_dir(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        self.assertTrue(out.is_dir())

    def test_output_dir_name_contains_target(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        self.assertIn("windows", out.name)

    def test_build_manifest_written(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        manifest_path = out / "build_manifest.json"
        self.assertTrue(manifest_path.exists())
        data = json.loads(manifest_path.read_text())
        self.assertEqual(data["game_name"], "Test Game")
        self.assertEqual(data["game_version"], "1.0.0")
        self.assertEqual(data["target"], "windows")

    def test_runtime_profile_stages_runtime_only_engine(self) -> None:
        plan = self._plan(runtime_profile=RuntimeProfile.PYGAME)
        packager = _NoopPackager(plan.target)
        out = self._export(plan, packager=packager)

        runtime_package = out / "runtime" / "python" / "Lib" / "site-packages" / "expra_engine"
        self.assertTrue((runtime_package / "core" / "engine.py").exists())
        self.assertTrue((runtime_package / "runtime" / "pygame_runtime.py").exists())
        self.assertFalse((runtime_package / "editor").exists())
        self.assertEqual(packager.packages, ["pygame>=2.6"])

        manifest = json.loads((out / "build_manifest.json").read_text())
        self.assertEqual(manifest["runtime_profile"], "pygame")

    def test_linux_runtime_profile_uses_python_specific_site_packages(self) -> None:
        plan = self._plan(
            target=ExportTarget.LINUX,
            runtime_profile=RuntimeProfile.PYGAME,
        )
        packager = _NoopPackager(plan.target)
        out = self._export(plan, packager=packager)

        runtime_package = out / "runtime" / "lib" / "python3.12" / "site-packages" / "expra_engine"
        self.assertTrue((runtime_package / "runtime" / "pygame_runtime.py").exists())

    def test_asset_manifest_written(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        asset_path = out / "asset_manifest.json"
        self.assertTrue(asset_path.exists())
        data = json.loads(asset_path.read_text())
        self.assertIn("entries", data)

    def test_verify_passes_after_export(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        verify_export(out)  # must not raise

    def test_assets_copied(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        game_dir = out / "Test_Game"
        self.assertTrue(game_dir.is_dir())
        self.assertTrue((game_dir / "assets" / "sprite.png").exists())

    def test_project_behaviour_script_is_packaged_without_editor_modules(self) -> None:
        scripts = self._project / "scripts"
        scripts.mkdir()
        (scripts / "player.py").write_text(
            "from expra_engine.runtime.behaviour import Behaviour\n"
            "class PlayerBehaviour(Behaviour):\n"
            "    pass\n"
        )
        out = self._export(self._plan())
        game_dir = out / "Test_Game"
        self.assertTrue((game_dir / "scripts" / "player.py").exists())
        self.assertFalse((game_dir / "editor").exists())

    def test_cancellation_raises(self) -> None:
        plan = self._plan()
        cancel = threading.Event()
        cancel.set()
        packager = _NoopPackager(plan.target)
        with self.assertRaises(ExportError):
            GameExporter(packager=packager).export(plan, cancel=cancel)

    def test_previous_build_intact_on_failure(self) -> None:
        # Do a successful export first
        plan = self._plan()
        first_out = self._export(plan)
        sentinel = first_out / "sentinel.txt"
        sentinel.write_text("was here")

        # Attempt to create a plan with a bad entry point — validation raises before export
        with self.assertRaises(ValueError):
            ExportPlan(
                project_dir=self._project,
                entry_point="nonexistent.py",
                output_dir=self._output,
                target=ExportTarget.WINDOWS,
                game_name="Test Game",
                game_version="1.0.0",
                python_version="3.12.4",
                arch=PythonArch.AMD64,
                compile_bytecode=False,
            )

        # Sentinel from first export must still be there (atomic temp -> promote)
        self.assertTrue(sentinel.exists())

    def test_promotion_failure_preserves_previous_build(self) -> None:
        plan = self._plan()
        first_out = self._export(plan)
        sentinel = first_out / "sentinel.txt"
        sentinel.write_text("was here")

        with patch(
            "expra_engine.export.exporter.shutil.copytree",
            side_effect=OSError("copy failed"),
        ), self.assertRaises(ExportError):
            self._export(plan)

        self.assertEqual(sentinel.read_text(), "was here")

    def test_duplicate_manifest_destinations_are_rejected(self) -> None:
        manifest = AssetManifest(
            entries=[
                AssetEntry("one.txt", 1, "a", destination="same.txt"),
                AssetEntry("two.txt", 1, "b", destination="same.txt"),
            ]
        )
        with self.assertRaises(ValueError):
            _merge_manifests(manifest)

    def test_progress_events_emitted(self) -> None:
        plan = self._plan()
        events: list[ExportProgressEvent] = []
        self._export(plan, progress=events.append)
        phases = {e.phase for e in events}
        self.assertIn(ExportPhase.PLANNING, phases)
        self.assertIn(ExportPhase.DONE, phases)

    def test_progress_percent_monotone(self) -> None:
        plan = self._plan()
        events: list[ExportProgressEvent] = []
        self._export(plan, progress=events.append)
        percents = [e.percent for e in events]
        self.assertEqual(percents[0], 0)
        self.assertEqual(percents[-1], 100)
        self.assertEqual(percents, sorted(percents))

    def test_linux_target(self) -> None:
        plan = self._plan(target=ExportTarget.LINUX)
        out = self._export(plan)
        self.assertIn("linux", out.name)

    def test_game_name_with_spaces(self) -> None:
        plan = self._plan(game_name="Space Adventure")
        out = self._export(plan)
        self.assertIn("Space_Adventure", out.name)

    def test_no_progress_callback(self) -> None:
        plan = self._plan()
        # Must not raise even without progress callback
        self._export(plan)

    def test_build_manifest_has_engine_version(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        data = json.loads((out / "build_manifest.json").read_text())
        self.assertIn("engine_version", data)
        self.assertIsInstance(data["engine_version"], str)

    def test_engine_version_prefers_source_when_metadata_is_stale(self) -> None:
        with patch("importlib.metadata.version", return_value="0.1.2.1"):
            self.assertEqual(_engine_version(), __version__)

    def test_build_manifest_has_timestamp(self) -> None:
        plan = self._plan()
        out = self._export(plan)
        data = json.loads((out / "build_manifest.json").read_text())
        ts = data.get("build_timestamp", "")
        self.assertTrue(ts.startswith("202"))  # ISO timestamp

    def test_runtime_manifest_uses_relative_mount_configuration(self) -> None:
        service = ResourceService(
            ResourceResolver(
                [
                    DirectoryMount(
                        self._project / "assets",
                        MountSpec(name="project-assets", scheme="assets"),
                    )
                ]
            )
        )
        plan = self._plan(
            resource_service=service,
            resource_ids=("assets://sprite.png",),
        )

        out = self._export(plan)
        self.assertTrue((out / "Test_Game" / "__main__.py").exists())
        runtime_manifest = json.loads((out / "runtime_manifest.json").read_text())
        self.assertEqual(runtime_manifest["mounts"][0]["source"], "resources")
        self.assertNotIn(str(self._project), json.dumps(runtime_manifest))


class TestGameExporterBytecode(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._project, self._output = _make_project(self._tmp)

    def test_compile_bytecode_removes_py(self) -> None:
        plan = ExportPlan(
            project_dir=self._project,
            entry_point="__main__.py",
            output_dir=self._output,
            target=ExportTarget.WINDOWS,
            game_name="BytecodeGame",
            game_version="1.0.0",
            python_version="3.12.4",
            arch=PythonArch.AMD64,
            compile_bytecode=True,
        )
        cancel = threading.Event()
        packager = _NoopPackager(ExportTarget.WINDOWS)
        out = GameExporter(packager=packager).export(plan, cancel=cancel)
        game_dir = out / "BytecodeGame"
        py_files = list(game_dir.rglob("*.py"))
        self.assertEqual(py_files, [], f"Expected no .py files, found: {py_files}")
        pyc_files = list(game_dir.rglob("*.pyc"))
        self.assertTrue(len(pyc_files) > 0, "Expected .pyc files after compilation")
