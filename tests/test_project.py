"""Tests for Project."""

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import (
    Level,
    LevelMetadata,
    Scene,
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
)
from expra_engine.core.scene.document_codec import (
    decode_protobuf_document,
    encode_protobuf,
)
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
            self.assertEqual(project.start_scene, "scenes/main.scene.pb")
            self.assertEqual(project.load_document().name, "Main")
            data = json.loads(project.project_file.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["entrypoint"], "scenes/main.scene.pb")
            self.assertEqual(data["game_version"], "0.1.0")

    def test_new_project_persists_its_starter_document_as_typed_pb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("PB Project", Path(tmp) / "project")
            self.assertEqual(project.entrypoint, "scenes/main.scene.pb")
            self.assertTrue(project.document_file().is_file())
            self.assertFalse((project.path / "scenes" / "main.json").exists())
            self.assertEqual(project.load_document().name, "Main")

    def test_pb_document_save_load_is_deterministic_and_extension_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("PB Project", Path(tmp) / "project")
            scene = Scene("Door", scene_id="door-1")
            scene.create_entity("Door Body", entity_id="door-body")
            path = "scenes/door.scene.pb"

            project.save_document(scene, path)
            first = project.document_file(path).read_bytes()
            loaded = project.load_document(path)
            project.save_document(loaded, path)
            second = project.document_file(path).read_bytes()

            self.assertEqual(first, second)
            self.assertEqual(decode_protobuf_document(first).scene_id, "door-1")
            with self.assertRaisesRegex(ProjectError, "extension"):
                project.save_document(scene, "levels/wrong.level.pb")

    def test_typed_pb_load_rejects_kind_mismatch_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("PB Project", Path(tmp) / "project")
            level = Level("Deepcore", scene_id="deepcore")
            wrong_kind_path = project.path / "scenes" / "wrong.scene.pb"
            wrong_kind_path.parent.mkdir(parents=True, exist_ok=True)
            wrong_kind_path.write_bytes(encode_protobuf(level))
            with self.assertRaisesRegex(ProjectError, "expected a scene document"):
                project.load_document("scenes/wrong.scene.pb")

            corrupt_path = project.path / "scenes" / "corrupt.scene.pb"
            corrupt_path.write_bytes(b"not a protobuf document")
            with self.assertRaisesRegex(ProjectError, "corrupt protobuf"):
                project.load_document("scenes/corrupt.scene.pb")

    def test_failed_document_load_does_not_publish_partial_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Atomic Load", Path(tmp) / "project")
            valid = Scene("Valid", scene_id="valid")
            project.save_scene(valid, "scenes/valid.json")
            project.load_document("scenes/valid.json")
            active = project.active_scene
            bad_path = project.path / "scenes" / "bad.json"
            bad_path.write_text(
                json.dumps(
                    {
                        "kind": "scene",
                        "scene_id": "bad",
                        "name": "Bad",
                        "entities": [{"entity_id": "partial"}],
                    }
                )
            )
            project.register_scene_path("scenes/bad.json")

            with self.assertRaises(ProjectError):
                project.load_document("scenes/bad.json")

            self.assertIs(project.active_scene, active)
            self.assertEqual(active.scene_id if active else None, "valid")

    def test_explicit_migration_writes_pb_and_preserves_legacy_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Migration", Path(tmp) / "project")
            source = Scene("Reusable Door", scene_id="door")
            project.save_scene(source, "scenes/door.json")
            main = Scene("Main", scene_id="main")
            root = main.create_entity("Door Instance", entity_id="door-instance")
            root.add_component(SceneInstanceComponent("scenes/door.json"))
            project.save_scene(main, "scenes/main.json")
            project._entrypoint = "scenes/main.json"
            project.register_scene_path("scenes/door.json")
            project.register_scene_path("scenes/main.json")
            project.save()

            mapping = project.migrate_to_protobuf()

            self.assertEqual(mapping["scenes/door.json"], "scenes/door.scene.pb")
            self.assertEqual(mapping["scenes/main.json"], "scenes/main.scene.pb")
            self.assertTrue((project.path / "scenes/door.json").is_file())
            self.assertTrue((project.path / "scenes/main.json").is_file())
            self.assertTrue((project.path / "scenes/main.scene.pb").is_file())
            self.assertEqual(project.entrypoint, "scenes/main.scene.pb")
            migrated = project.load_document("scenes/main.scene.pb")
            instance = migrated.find_entity("door-instance")
            assert instance is not None
            component = instance.get_component(SceneInstanceComponent)
            assert component is not None
            self.assertEqual(component.source_path, "scenes/door.scene.pb")

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

    def test_canonical_manifest_separates_resource_and_script_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "levels").mkdir()
            (root / "scripts").mkdir()
            (root / "project.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "Canonical",
                        "entrypoint": "levels/main.level.json",
                        "script_entry_point": "scripts/game.py",
                        "scenes": ["scenes/room.scene.json"],
                        "levels": ["levels/main.level.json"],
                    }
                )
            )

            project = Project.load(root)

            self.assertEqual(project.entrypoint, "levels/main.level.json")
            self.assertEqual(project.start_scene, "levels/main.level.json")
            self.assertEqual(project.script_entry_point, "scripts/game.py")
            self.assertEqual(project.entry_point, "scripts/game.py")
            self.assertEqual(project.to_dict()["entrypoint"], "levels/main.level.json")
            self.assertNotIn("start_scene", project.to_dict())
            self.assertNotIn("entry_point", project.to_dict())

    def test_legacy_manifest_migrates_in_memory_without_rewriting_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scenes").mkdir()
            (root / "scripts").mkdir()
            manifest = {
                "name": "Legacy",
                "start_scene": "scenes/main.json",
                "entry_point": "game.py",
            }
            manifest_path = root / "project.json"
            manifest_path.write_text(json.dumps(manifest))

            project = Project.load(root)

            self.assertEqual(project.entrypoint, "scenes/main.json")
            self.assertEqual(project.script_entry_point, "game.py")
            self.assertEqual(json.loads(manifest_path.read_text()), manifest)

    def test_conflicting_canonical_and_legacy_entrypoints_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.json").write_text(
                json.dumps(
                    {
                        "name": "Conflict",
                        "entrypoint": "scenes/canonical.json",
                        "start_scene": "scenes/legacy.json",
                    }
                )
            )

            with self.assertRaisesRegex(ProjectError, "entrypoint"):
                Project.load(root)

    def test_document_io_dispatches_level_without_creating_a_second_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Documents", Path(tmp) / "project")
            level = Level(
                "Main Level",
                scene_id="level-1",
                level_metadata=LevelMetadata(display_name="Main"),
            )
            level.create_entity("Player", entity_id="player")

            project.save_document(level, "levels/main.level.pb")
            loaded = project.load_document("levels/main.level.pb")

            self.assertIsInstance(loaded, Level)
            self.assertIs(loaded.entities[0].__class__, level.entities[0].__class__)
            self.assertEqual(loaded.level_metadata.display_name, "Main")  # type: ignore[union-attr]

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
            project.register_scene_path("scenes/a.json")
            project.register_scene_path("scenes/a.json")
            self.assertEqual(project.scene_paths().count("scenes/a.json"), 1)


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


class TestProjectSceneInstances(unittest.TestCase):
    """Project-level load/save integration for reusable scene instances."""

    def _make_project(self, tmp: str) -> Project:
        project = Project.create("Instances", Path(tmp) / "proj")
        room = Scene("Room Segment", scene_id="room-segment")
        wall = room.create_entity("Wall")
        wall.add_component(TransformComponent(x=1.0))
        project.save_scene(room, "scenes/room_segment.json")

        level = Scene("Level", scene_id="level")
        root = level.create_entity("Room Instance", entity_id="root-e")
        root.add_component(SceneInstanceComponent("scenes/room_segment.json"))
        project.save_scene(level, "scenes/main.json")
        return project

    def test_load_scene_resolves_instance_and_save_scene_omits_materialized_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._make_project(tmp)

            loaded = project.load_scene("scenes/main.json")
            self.assertEqual({e.name for e in loaded.entities}, {"Room Instance", "Wall"})

            project.save_scene(loaded, "scenes/main.json")
            on_disk = json.loads(
                (project.path / "scenes" / "main.json").read_text(encoding="utf-8")
            )
            self.assertEqual([e["name"] for e in on_disk["entities"]], ["Room Instance"])

    def test_source_identity_reflects_edits_to_source_scene_on_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._make_project(tmp)

            room = project.load_scene("scenes/room_segment.json")
            room.create_entity("New Prop")
            project.save_scene(room, "scenes/room_segment.json")

            reloaded = project.load_scene("scenes/main.json")
            self.assertIn("New Prop", {e.name for e in reloaded.entities})

    def test_missing_source_scene_raises_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Broken", Path(tmp) / "proj")
            level = Scene("Level")
            root = level.create_entity("Bad Instance")
            root.add_component(SceneInstanceComponent("scenes/does_not_exist.json"))
            project.save_scene(level, "scenes/main.json")

            with self.assertRaises(SceneInstanceSourceError) as ctx:
                project.load_scene("scenes/main.json")
            self.assertIn("Bad Instance", str(ctx.exception))

    def test_two_scene_cycle_raises_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Cyclic", Path(tmp) / "proj")

            scene_a = Scene("A")
            a_root = scene_a.create_entity("A Instance")
            a_root.add_component(SceneInstanceComponent("scenes/b.json"))
            project.save_scene(scene_a, "scenes/a.json")

            scene_b = Scene("B")
            b_root = scene_b.create_entity("B Instance")
            b_root.add_component(SceneInstanceComponent("scenes/a.json"))
            project.save_scene(scene_b, "scenes/b.json")

            with self.assertRaises(SceneInstanceCycleError):
                project.load_scene("scenes/a.json")

    def test_nested_instances_resolve_through_project_load_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._make_project(tmp)

            middle = Scene("Middle")
            middle_root = middle.create_entity("Middle Instance")
            middle_root.add_component(SceneInstanceComponent("scenes/main.json"))
            project.save_scene(middle, "scenes/middle.json")

            outer = Scene("Outer")
            outer_root = outer.create_entity("Outer Instance")
            outer_root.add_component(SceneInstanceComponent("scenes/middle.json"))
            project.save_scene(outer, "scenes/outer.json")

            loaded = project.load_scene("scenes/outer.json")
            self.assertEqual(
                {e.name for e in loaded.entities},
                {"Outer Instance", "Middle Instance", "Room Instance", "Wall"},
            )


if __name__ == "__main__":
    unittest.main()
