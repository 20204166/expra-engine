"""Tests for ExportPlan validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch
from expra_engine.filesystem import ResourceId


def _make_project(tmp: str) -> tuple[Path, Path]:
    project = Path(tmp) / "my_game"
    project.mkdir()
    (project / "__main__.py").write_text("print('hello')")
    output = Path(tmp) / "builds"
    output.mkdir()
    return project, output


class TestExportPlanValidation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._project, self._output = _make_project(self._tmp)

    def _plan(self, **overrides: object) -> ExportPlan:
        defaults: dict = {
            "project_dir": self._project,
            "entry_point": "__main__.py",
            "output_dir": self._output,
            "target": ExportTarget.WINDOWS,
            "game_name": "My Game",
            "game_version": "1.0.0",
            "python_version": "3.12.4",
        }
        defaults.update(overrides)
        return ExportPlan(**defaults)  # type: ignore[arg-type]

    # --- happy path ---

    def test_valid_plan_created(self) -> None:
        plan = self._plan()
        self.assertEqual(plan.game_name, "My Game")
        self.assertEqual(plan.target, ExportTarget.WINDOWS)
        self.assertEqual(plan.arch, PythonArch.AMD64)
        self.assertTrue(plan.compile_bytecode)

    def test_linux_target(self) -> None:
        plan = self._plan(target=ExportTarget.LINUX)
        self.assertEqual(plan.target.value, "linux")

    def test_frozen(self) -> None:
        plan = self._plan()
        with self.assertRaises((AttributeError, TypeError)):
            plan.game_name = "Other"  # type: ignore[misc]

    # --- validation failures ---

    def test_missing_project_dir(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(project_dir=Path("/nonexistent/nowhere"))

    def test_missing_entry_point(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(entry_point="missing.py")

    def test_invalid_game_name_empty(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(game_name="")

    def test_invalid_game_name_starts_with_dash(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(game_name="-bad")

    def test_invalid_game_name_special_chars(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(game_name="my/game")

    def test_invalid_game_version(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(game_version="not-a-version")

    def test_invalid_python_version_two_parts(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(python_version="3.12")

    def test_invalid_python_version_non_numeric(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(python_version="3.12.alpha")

    def test_relative_output_dir_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._plan(output_dir=Path("relative/path"))

    # --- edge cases ---

    def test_game_name_with_spaces_allowed(self) -> None:
        plan = self._plan(game_name="Space Invaders 2")
        self.assertEqual(plan.game_name, "Space Invaders 2")

    def test_game_name_alphanumeric_only(self) -> None:
        plan = self._plan(game_name="Roguelite2025")
        self.assertEqual(plan.game_name, "Roguelite2025")

    def test_extra_packages_tuple(self) -> None:
        plan = self._plan(extra_packages=("pillow==10.0.0", "numpy"))
        self.assertEqual(len(plan.extra_packages), 2)

    def test_exclude_patterns_frozenset(self) -> None:
        plan = self._plan(exclude_patterns=frozenset({"debug/", "test/"}))
        self.assertIn("debug/", plan.exclude_patterns)

    def test_logical_resources_are_part_of_the_plan(self) -> None:
        plan = self._plan(resource_ids=("package://demo/texture.png",))
        self.assertEqual(plan.resource_ids, (ResourceId.parse("package://demo/texture.png"),))


class TestExportTarget(unittest.TestCase):
    def test_value_string(self) -> None:
        self.assertEqual(ExportTarget.WINDOWS.value, "windows")
        self.assertEqual(ExportTarget.LINUX.value, "linux")

    def test_from_string(self) -> None:
        self.assertEqual(ExportTarget("windows"), ExportTarget.WINDOWS)


class TestPythonArch(unittest.TestCase):
    def test_amd64(self) -> None:
        self.assertEqual(PythonArch.AMD64.value, "amd64")

    def test_arm64(self) -> None:
        self.assertEqual(PythonArch.ARM64.value, "arm64")
