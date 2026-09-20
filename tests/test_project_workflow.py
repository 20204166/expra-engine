"""Headless real-project workflow coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.editor.script_tools import attach_script, create_behaviour_script
from expra_engine.runtime import ScriptComponent, ScriptRegistry
from expra_engine.runtime.input import PhysicalInput


class TestProjectWorkflow(unittest.TestCase):
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
