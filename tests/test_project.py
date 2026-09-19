"""Tests for Project."""

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene


class TestProjectCreateAndSave(unittest.TestCase):
    def test_create_makes_directory_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "my_project"
            project = Project.create("My Game", path)
            self.assertTrue(project.project_file.exists())
            self.assertTrue(project.scenes_dir.exists())
            self.assertTrue(project.assets_dir.exists())

    def test_save_writes_project_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proj"
            project = Project.create("Demo", path)
            project.register_scene_path("scenes/level1.json")
            project.save()
            data = json.loads(project.project_file.read_text())
            self.assertEqual(data["name"], "Demo")
            self.assertIn("scenes/level1.json", data["scenes"])

    def test_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game"
            project = Project.create("Space Game", path)
            project.register_scene_path("scenes/intro.json")
            project.save()

            loaded = Project.load(path)
            self.assertEqual(loaded.name, "Space Game")
            self.assertIn("scenes/intro.json", loaded.scene_paths())

    def test_register_scene_path_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project("Game", Path(tmp))
            project.register_scene_path("s/a.json")
            project.register_scene_path("s/a.json")
            self.assertEqual(project.scene_paths().count("s/a.json"), 1)


class TestProjectActiveScene(unittest.TestCase):
    def test_set_active_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project("G", Path(tmp))
            scene = Scene("Level 1")
            project.set_active_scene(scene)
            self.assertIs(project.active_scene, scene)

    def test_active_scene_initially_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project("G", Path(tmp))
            self.assertIsNone(project.active_scene)


if __name__ == "__main__":
    unittest.main()
