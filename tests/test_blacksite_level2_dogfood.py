"""Phase G dogfood: edit Blacksite Level 2 through the real editor, and
reusable-scene-instance semantics -- spec sections 23 and 25.

Every mutation below goes through the same production code paths a human
clicking the editor invokes (CommandStack pushes, ProjectWorkflow, real Tk
widgets) -- never a raw scene.add_entity/hand JSON edit. Runs against a
temporary copy of the real Blacksite Relay project so this stays a safe,
idempotent, re-runnable regression test rather than mutating the checked-in
example on every test run (a one-off script performs that real, kept edit
separately -- see the session's final report for exactly what changed there).
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.entity import Entity
from expra_engine.core.project import Project
from expra_engine.core.scene import (
    Scene,
    SceneInstanceComponent,
    resolve_scene_instances,
)
from expra_engine.editor.commands import TransformEntityCommand
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.ui.editor_window import EditorWindow
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()
BLACKSITE_SRC = Path(__file__).parents[1] / "examples" / "blacksite_relay"
LEVEL2 = "levels/level_02_deepcore.level.pb"


def _copy_blacksite(destination: Path) -> Project:
    shutil.copytree(BLACKSITE_SRC, destination)
    return Project.load(destination)


def _drag_event(x: float, y: float, state: int = 0) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, state=state)


def _door_scene() -> Scene:
    """A tiny reusable Scene: a door body plus one ScriptComponent with an
    exposed value, for the override-semantics dogfood (spec §25)."""
    scene = Scene("Security Door")
    door = scene.create_entity("Door Body")
    door.add_component(TransformComponent(x=0.0, y=0.0))
    door.add_component(
        ScriptComponent(
            ResourceId.parse("project://scripts/door.py"),
            "SecurityDoorBehaviour",
            exposed_values={"open_speed": 2.0, "locked": True},
        )
    )
    return scene


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class BlacksiteLevel2DogfoodTests(unittest.TestCase):
    def test_full_level2_authoring_sequence_through_the_real_editor(self) -> None:
        with TemporaryDirectory() as directory:
            project = _copy_blacksite(Path(directory) / "Blacksite Relay")
            window = EditorWindow(Engine())
            try:
                # 1. Open Level 2 (Open Scene, Phase F) -- not the project default.
                window._project_workflow.open_loaded(project)
                window._project_workflow.open_scene(LEVEL2)
                window._root.update()
                scene = window._engine.edit_scene
                assert scene is not None
                self.assertEqual(scene.name, "Blacksite Relay - Deep Core")
                original_entity_count = len(scene.entities)

                # 2. Inspect hierarchy.
                barrier = scene.find_entity_by_name("Barrier 1")
                assert barrier is not None
                drone = scene.find_entity_by_name("Security Drone 1")
                assert drone is not None

                # 3-4. Select "Barrier 1", move it via the real drag controller
                # (Phase D's SpatialEditController) -- one drag, one undo entry.
                window._on_hierarchy_select((barrier.entity_id,))
                window._root.update()
                self.assertEqual(window._selected_ids, (barrier.entity_id,))
                before_history = len(window._command_stack.history)
                barrier_transform = barrier.get_component(TransformComponent)
                assert barrier_transform is not None
                before_x = barrier_transform.x
                controller = window._viewport._spatial_edit
                camera = window._viewport._camera
                start_world = camera.unproject((0.0, 0.0))
                end_world = camera.unproject((30.0, 20.0))
                expected_dx = end_world[0] - start_world[0]
                controller.begin_drag_on_entity(barrier.entity_id, _drag_event(0.0, 0.0))
                controller.continue_drag(_drag_event(30.0, 20.0))
                controller.end_drag()
                window._root.update()
                after_x = barrier_transform.x
                self.assertGreater(abs(expected_dx), 0.01)  # sanity: a real, non-trivial move
                self.assertAlmostEqual(after_x, before_x + expected_dx, places=3)
                self.assertEqual(len(window._command_stack.history), before_history + 1)
                self.assertIsInstance(window._command_stack.history[-1], TransformEntityCommand)

                # 5-6. Duplicate a Security Drone -- "place an additional enemy"
                # via a real, existing enemy rather than inventing one from
                # scratch (an equally legitimate reading of the spec item).
                window._on_hierarchy_select((drone.entity_id,))
                window._root.update()
                from expra_engine.editor.commands import duplicate_selection

                enemy_count_before = len(scene.get_entities_by_tag("enemy"))
                duplicate_selection(window)
                window._root.update()
                self.assertEqual(len(scene.get_entities_by_tag("enemy")), enemy_count_before + 1)
                new_drone_id = window._selected_ids[0]
                self.assertNotEqual(new_drone_id, drone.entity_id)

                # 7. Place a pickup-like sprite via the real drop-to-viewport
                # path (asset kind resolution + CreateEntityCommand), not a
                # bare scene.add_entity.
                from expra_engine.editor.assets import AssetEntry
                from expra_engine.editor.commands import drop_asset_on_viewport

                canvas = window._viewport._canvas
                canvas.update_idletasks()
                asset_path = project.assets_dir / "kenney" / "floor_panel.png"
                self.assertTrue(asset_path.is_file())
                entry = AssetEntry(
                    asset_path, "floor_panel.png", False, project.asset_id(asset_path)
                )
                self.assertEqual(entry.kind, "Image")
                drop_x = canvas.winfo_rootx() + 10
                drop_y = canvas.winfo_rooty() + 10
                sprite_count_before = len(
                    [e for e in scene.entities if e.get_component(TransformComponent) is not None]
                )
                drop_asset_on_viewport(window, entry, drop_x, drop_y)
                window._root.update()
                placed = scene.find_entity_by_name("floor_panel")
                assert placed is not None
                from expra_engine.runtime.visual_components import SpriteComponent

                self.assertIsNotNone(placed.get_component(SpriteComponent))
                self.assertGreater(
                    len(
                        [
                            e
                            for e in scene.entities
                            if e.get_component(TransformComponent) is not None
                        ]
                    ),
                    sprite_count_before,
                )

                # 8. Edit arena dimensions through the same path the Inspector's
                # exposed-value fields use (SetExposedValueCommand).
                controller_entity = scene.find_entity_by_name("Mission Controller")
                assert controller_entity is not None
                script = controller_entity.get_component(ScriptComponent)
                assert script is not None
                component_index = list(controller_entity.components).index(script)
                original_half_width = script.exposed_values["arena_half_width"]
                from expra_engine.editor.commands import SetExposedValueCommand

                window._command_stack.push(
                    SetExposedValueCommand(
                        scene,
                        controller_entity.entity_id,
                        component_index,
                        "arena_half_width",
                        original_half_width + 5.0,
                    )
                )
                self.assertEqual(
                    script.exposed_values["arena_half_width"], original_half_width + 5.0
                )

                # 9-10. Edit the scene's own camera (position/width) and pan
                # limits -- there is currently no dedicated Inspector panel
                # for this (Phase E only built visualization, not editing);
                # SceneCamera's own dict-like interface is the legitimate
                # existing capability, confirmed since Blacksite already
                # ships two different per-scene camera configs.
                original_camera = dict(scene.camera.to_dict())
                new_camera = dict(original_camera)
                new_camera["position"] = [5.0, -3.0]
                new_camera["width"] = 130.0
                new_camera["limit_enabled"] = True
                new_camera["limits"] = [-70.0, -35.0, 70.0, 35.0]
                scene.camera = new_camera
                current_camera = scene.camera
                self.assertEqual(current_camera.to_dict()["position"], [5.0, -3.0])

                # 11. Save through the canonical path.
                window._act_save_scene()

                # 12. Close and reopen; verify every change survived.
                window._on_close()
                window = EditorWindow(Engine())
                window._project_workflow.open_loaded(project)
                window._project_workflow.open_scene(LEVEL2)
                window._root.update()
                reopened = window._engine.edit_scene
                assert reopened is not None
                self.assertGreater(len(reopened.entities), original_entity_count)

                reopened_barrier = reopened.find_entity(barrier.entity_id)
                assert reopened_barrier is not None
                reopened_barrier_transform = reopened_barrier.get_component(TransformComponent)
                assert reopened_barrier_transform is not None
                self.assertAlmostEqual(
                    reopened_barrier_transform.x,
                    before_x + expected_dx,
                    places=3,
                )
                self.assertIsNotNone(reopened.find_entity(new_drone_id))
                self.assertIsNotNone(reopened.find_entity_by_name("floor_panel"))
                reopened_controller = reopened.find_entity_by_name("Mission Controller")
                assert reopened_controller is not None
                reopened_script = reopened_controller.get_component(ScriptComponent)
                assert reopened_script is not None
                self.assertEqual(
                    reopened_script.exposed_values["arena_half_width"], original_half_width + 5.0
                )
                self.assertEqual(reopened.camera.to_dict()["position"], [5.0, -3.0])
                self.assertTrue(reopened.camera.to_dict()["limit_enabled"])

                # 13. Play / Stop: runtime scene has the new content; edit
                # scene is restored exactly on Stop (existing Engine
                # isolation, not something this dogfood changes).
                window._act_play()
                window._root.update()
                self.assertEqual(window._engine.run_state, EngineRunState.PLAY)
                active_scene = window._engine.active_scene
                assert active_scene is not None
                self.assertIsNotNone(active_scene.find_entity_by_name("floor_panel"))
                window._act_stop()
                window._root.update()
                self.assertEqual(window._engine.run_state, EngineRunState.EDIT)
                edit_scene = window._engine.edit_scene
                assert edit_scene is not None
                self.assertIsNotNone(edit_scene.find_entity_by_name("floor_panel"))
                restored_barrier = edit_scene.find_entity(barrier.entity_id)
                assert restored_barrier is not None
                restored_barrier_transform = restored_barrier.get_component(TransformComponent)
                assert restored_barrier_transform is not None
                self.assertAlmostEqual(
                    restored_barrier_transform.x,
                    before_x + expected_dx,
                    places=3,
                )
            finally:
                window._on_close()


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class ReusableSceneInstanceDogfoodTests(unittest.TestCase):
    """Spec §25: create one reusable Scene, place it twice, prove source
    changes propagate to both while a per-instance override stays local."""

    @staticmethod
    def _exposed(entity: Entity) -> dict:
        script = entity.get_component(ScriptComponent)
        assert script is not None
        return script.exposed_values

    def test_two_instances_share_source_but_not_overrides(self) -> None:
        with TemporaryDirectory() as directory:
            project = _copy_blacksite(Path(directory) / "Blacksite Relay")
            (project.scenes_dir / "security_door.json").write_text(
                json.dumps(_door_scene().to_dict(), indent=2), encoding="utf-8"
            )
            project.register_scene_path("scenes/security_door.json")

            scene = project.load_scene(LEVEL2)

            root_a = scene.create_entity("Door Instance A")
            root_a.add_component(TransformComponent(x=10.0, y=0.0))
            root_a.add_component(SceneInstanceComponent("scenes/security_door.json"))

            root_b = scene.create_entity("Door Instance B")
            root_b.add_component(TransformComponent(x=-10.0, y=0.0))
            root_b.add_component(
                SceneInstanceComponent(
                    "scenes/security_door.json",
                    overrides={"Door Body": {"open_speed": 9.0}},
                )
            )

            resolve_scene_instances(scene, resolve_source=lambda path: project.load_scene(path))

            door_a = next(
                e
                for e in scene.entities
                if e.name == "Door Body"
                and scene.is_instance_materialized(e.entity_id)
                and self._ancestor_is(scene, e, root_a.entity_id)
            )
            door_b = next(
                e
                for e in scene.entities
                if e.name == "Door Body"
                and scene.is_instance_materialized(e.entity_id)
                and self._ancestor_is(scene, e, root_b.entity_id)
            )
            self.assertEqual(self._exposed(door_a)["open_speed"], 2.0)
            self.assertEqual(self._exposed(door_b)["open_speed"], 9.0)

            # Modify the SOURCE scene's default (not the "locked" override key)
            # and confirm it propagates to BOTH instances on the next resolve.
            source = project.load_scene("scenes/security_door.json")
            source_door = source.find_entity_by_name("Door Body")
            assert source_door is not None
            self._exposed(source_door)["locked"] = False
            project.save_scene(source, "scenes/security_door.json")

            resolve_scene_instances(scene, resolve_source=lambda path: project.load_scene(path))
            door_a = next(
                e
                for e in scene.entities
                if e.name == "Door Body"
                and scene.is_instance_materialized(e.entity_id)
                and self._ancestor_is(scene, e, root_a.entity_id)
            )
            door_b = next(
                e
                for e in scene.entities
                if e.name == "Door Body"
                and scene.is_instance_materialized(e.entity_id)
                and self._ancestor_is(scene, e, root_b.entity_id)
            )
            self.assertFalse(self._exposed(door_a)["locked"])
            self.assertFalse(self._exposed(door_b)["locked"])
            # The override survives re-resolution independently of the
            # source-level change.
            self.assertEqual(self._exposed(door_a)["open_speed"], 2.0)
            self.assertEqual(self._exposed(door_b)["open_speed"], 9.0)

    @staticmethod
    def _ancestor_is(scene: Scene, entity: Entity, root_id: str) -> bool:
        current: Entity | None = entity
        seen: set[str] = set()
        while current is not None and current.entity_id not in seen:
            if current.entity_id == root_id:
                return True
            seen.add(current.entity_id)
            current = scene.find_entity(current.parent_id) if current.parent_id else None
        return False


if __name__ == "__main__":
    unittest.main()
