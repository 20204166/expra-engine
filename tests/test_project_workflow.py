"""Headless real-project workflow coverage."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.editor.script_tools import attach_script, create_behaviour_script
from expra_engine.runtime import ScriptComponent, ScriptRegistry
from expra_engine.runtime.input import PhysicalInput


class TestProjectWorkflow(unittest.TestCase):
    def test_run_project_launches_the_project_script_as_a_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            engine = SimpleNamespace(project=project)
            window = SimpleNamespace(_engine=engine, _console=MagicMock(), _root=MagicMock())
            workflow = ProjectWorkflow(window)

            with patch("expra_engine.editor.project_workflow.subprocess.Popen") as launch:
                workflow.run_project()

            launch.assert_called_once_with(
                [sys.executable, str(project.path / "__main__.py")],
                cwd=project.path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertIs(workflow._project_process, launch.return_value)

    def test_stop_project_terminates_a_running_child_process(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        workflow._project_process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)
        self.assertIsNone(workflow._project_process)

    def test_stop_project_kills_a_child_that_does_not_terminate(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("game", 2), None]
        workflow._project_process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertIsNone(workflow._project_process)

    def test_new_project_has_standard_runtime_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            entry_point = project.path / "__main__.py"
            self.assertTrue(entry_point.is_file())
            self.assertIn("run_project", entry_point.read_text(encoding="utf-8"))

    def test_create_script_attach_save_close_reopen_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Workflow", Path(tmp) / "workflow")
            scene = project.load_scene()
            entity = scene.create_entity("Player")
            entity.add_component(TransformComponent())
            script_id = create_behaviour_script(
                project.path, "scripts/player.py", "PlayerBehaviour"
            )
            attach_script(entity, script_id, "PlayerBehaviour")
            project.save_scene(scene)

            reopened = Project.load(project.path)
            loaded_scene = reopened.load_scene()
            loaded_entity = loaded_scene.find_entity(entity.entity_id)
            assert loaded_entity is not None
            component = loaded_entity.components[-1]
            assert isinstance(component, ScriptComponent)
            self.assertEqual(str(component.script_id), "project://scripts/player.py")
            self.assertIsNotNone(
                ScriptRegistry(reopened.path).resolve(component.script_id, "PlayerBehaviour")
            )

    def test_project_relocation_keeps_logical_script_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a" / "game"
            project = Project.create("Game", source)
            create_behaviour_script(project.path, "scripts/player.py", "PlayerBehaviour")
            relocated = Path(tmp) / "b" / "game"
            relocated.parent.mkdir()
            source.rename(relocated)
            reopened = Project.load(relocated)
            self.assertIsNotNone(
                ScriptRegistry(reopened.path).resolve(
                    "project://scripts/player.py", "PlayerBehaviour"
                )
            )

    def test_imports_audio_as_a_project_asset_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Audio Game", root / "game")
            source = root / "theme.ogg"
            source.write_bytes(b"fake audio")
            resource = project.import_asset(source, "audio/theme.ogg")
            self.assertEqual(str(resource), "assets://audio/theme.ogg")
            self.assertEqual((project.assets_dir / "audio/theme.ogg").read_bytes(), b"fake audio")
            with self.assertRaises(ValueError):
                project.import_asset(source, "audio/theme.ogg")

    def test_input_settings_are_project_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Input Game", Path(tmp) / "game")
            project.set_input_binding("move_left", "keyboard:left")
            project.save()
            reopened = Project.load(project.path)
            self.assertEqual(reopened.input_settings, {"move_left": "keyboard:left"})
            engine = Engine()
            engine.set_project(reopened)
            self.assertEqual(len(engine.input_map.press(PhysicalInput("keyboard", "left"))), 1)


if __name__ == "__main__":
    unittest.main()
