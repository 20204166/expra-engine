"""Tests for Project."""

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Scene
from expra_engine.filesystem import ResourceId


class TestProjectCreateAndSave(unittest.TestCase):
    def test_asset_path_has_stable_project_relative_logical_id(self) -> None:
        project = Project("Game", Path("/project"))

        self.assertEqual(
            project.asset_id(Path("textures") / "player.png"),
            ResourceId.parse("assets://textures/player.png"),
        )

    def test_resource_service_mounts_assets_without_loading_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Game", Path(tmp) / "project")
            service = project.resource_service()

            self.assertIsNone(getattr(project, "_resource_service", None))
            mount = service.resolver.mount_for("project-assets")
            self.assertIsNotNone(mount)
            assert mount is not None
            self.assertEqual(mount.spec.scheme, "assets")

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

    def test_create_builds_real_project_layout_and_starter_scene_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("My Game", Path(tmp) / "My Game")
            self.assertTrue(project.scripts_dir.is_dir())
            self.assertEqual(project.start_scene, "scenes/main.json")
            self.assertEqual(project.load_scene().name, "Main")
            data = json.loads(project.project_file.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["game_version"], "0.1.0")

    def test_create_rejects_non_empty_destination_without_touching_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "existing"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_text("keep")
            with self.assertRaises(ProjectError):
                Project.create("Game", destination)
            self.assertEqual(marker.read_text(), "keep")

    def test_load_accepts_legacy_manifest_and_rejects_future_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scenes").mkdir()
            (root / "assets").mkdir()
            (root / "scripts").mkdir()
            (root / "scenes" / "main.json").write_text(json.dumps(Scene("Main").to_dict()))
            (root / "project.json").write_text(
                json.dumps({"name": "Legacy", "scenes": ["scenes/main.json"]})
            )
            legacy = Project.load(root)
            self.assertEqual(legacy.start_scene, "scenes/main.json")
            (root / "project.json").write_text(
                json.dumps({"schema_version": 99, "name": "Future", "scenes": []})
            )
            with self.assertRaises(ProjectError):
                Project.load(root)

    def test_scene_paths_cannot_escape_project(self) -> None:
        project = Project("Game", Path("/tmp/game"))
        with self.assertRaises(ProjectError):
            project.set_start_scene("scenes/../secret.json")

    def test_scene_folder_singular_is_supported(self) -> None:
        project = Project("Game", Path("/tmp/game"))

        project.set_start_scene("scene/main.json")

        self.assertEqual(project.start_scene, "scene/main.json")
        self.assertEqual(project.scenes_dir, project.path / "scene")

    def test_project_input_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Input Game", Path(tmp) / "input-game")
            project.input_settings["move_left"] = "keyboard:left"
            project.save()
            loaded = Project.load(project.path)
            self.assertEqual(loaded.input_settings["move_left"], "keyboard:left")

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
