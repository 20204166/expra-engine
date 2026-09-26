"""Tests for reusable Scene composition (SceneInstanceComponent / resolve_scene_instances)."""

from __future__ import annotations

import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import (
    Level,
    Scene,
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
    resolve_scene_instances,
)
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.script_component import ScriptComponent


def _source_scene() -> Scene:
    """A small two-entity hierarchy: 'Wall' (root) with child 'Door A' (a script entity)."""
    scene = Scene("Room Segment", scene_id="room-segment")
    wall = scene.create_entity("Wall")
    wall.add_component(TransformComponent(x=1.0, y=2.0))
    door = scene.create_entity("Door A", parent_id=wall.entity_id)
    door.add_component(
        ScriptComponent(
            ResourceId.parse("project://scripts/door.py"),
            "DoorBehaviour",
            exposed_values={"open_speed": 2.0},
        )
    )
    return scene


def _owning_scene_with_instance(
    *, overrides: dict[str, dict[str, object]] | None = None
) -> tuple[Scene, str]:
    scene = Scene("Level", scene_id="level")
    root = scene.create_entity("Room Instance")
    root.add_component(TransformComponent(x=10.0, y=0.0))
    root.add_component(SceneInstanceComponent("scenes/room_segment.json", overrides=overrides))
    return scene, root.entity_id


class TestSceneInstanceComponent(unittest.TestCase):
    def test_blank_source_path_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SceneInstanceComponent("")

    def test_round_trip_dict(self) -> None:
        component = SceneInstanceComponent(
            "scenes/door.json", overrides={"Door A": {"open_speed": 4.0}}
        )
        restored = SceneInstanceComponent.from_dict(component.to_dict())
        self.assertEqual(restored.source_path, "scenes/door.json")
        self.assertEqual(restored.overrides, {"Door A": {"open_speed": 4.0}})

    def test_non_json_serializable_overrides_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SceneInstanceComponent("scenes/x.json", overrides={"A": {"k": object()}})


class TestResolveSceneInstances(unittest.TestCase):
    def test_level_sources_are_rejected_as_scene_instances(self) -> None:
        scene, _root_id = _owning_scene_with_instance()

        with self.assertRaisesRegex(SceneInstanceSourceError, "must be Scene documents"):
            resolve_scene_instances(scene, resolve_source=lambda _path: Level("Level"))

    def test_resolving_materializes_source_hierarchy_as_children(self) -> None:
        scene, root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        names = {e.name for e in scene.entities}
        self.assertEqual(names, {"Room Instance", "Wall", "Door A"})

        wall = scene.find_entity_by_name("Wall")
        door = scene.find_entity_by_name("Door A")
        assert wall is not None and door is not None
        self.assertEqual(wall.parent_id, root_id)
        self.assertEqual(door.parent_id, wall.entity_id)
        self.assertTrue(scene.is_instance_materialized(wall.entity_id))
        self.assertTrue(scene.is_instance_materialized(door.entity_id))
        self.assertFalse(scene.is_instance_materialized(root_id))
        # Materialized entities get fresh ids, never the source's own ids.
        source = _source_scene()
        source_ids = {e.entity_id for e in source.entities}
        self.assertNotIn(wall.entity_id, source_ids)

    def test_root_transform_composes_through_to_materialized_children(self) -> None:
        scene, _root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        wall = scene.find_entity_by_name("Wall")
        assert wall is not None
        # Root is at (10, 0); source Wall's local transform is (1, 2).
        self.assertEqual(scene.world_pose(wall.entity_id), (11.0, 2.0, 0.0))

    def test_to_dict_default_includes_everything(self) -> None:
        scene, _root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        names = {e["name"] for e in scene.to_dict()["entities"]}
        self.assertEqual(names, {"Room Instance", "Wall", "Door A"})

    def test_to_dict_excluding_instance_content_omits_materialized_descendants(self) -> None:
        scene, _root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        entities = scene.to_dict(include_instance_content=False)["entities"]
        names = {e["name"] for e in entities}
        self.assertEqual(names, {"Room Instance"})
        # The persisted root entity still carries its SceneInstanceComponent.
        (root_data,) = entities
        self.assertIn("scene_instance", {c["type"] for c in root_data["components"]})

    def test_exposed_value_overrides_apply_to_named_materialized_entity(self) -> None:
        scene, _root_id = _owning_scene_with_instance(overrides={"Door A": {"open_speed": 9.5}})
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        door = scene.find_entity_by_name("Door A")
        assert door is not None
        script = door.get_component(ScriptComponent)
        assert script is not None
        self.assertEqual(script.exposed_values["open_speed"], 9.5)

    def test_missing_source_raises_explicit_error_naming_entity_and_path(self) -> None:
        scene, _root_id = _owning_scene_with_instance()

        def _fail(_path: str) -> Scene:
            raise FileNotFoundError("no such scene")

        with self.assertRaises(SceneInstanceSourceError) as ctx:
            resolve_scene_instances(scene, resolve_source=_fail)
        self.assertIn("Room Instance", str(ctx.exception))
        self.assertIn("scenes/room_segment.json", str(ctx.exception))

    def test_cycle_via_chain_raises_explicit_error(self) -> None:
        scene, _root_id = _owning_scene_with_instance()

        with self.assertRaises(SceneInstanceCycleError) as ctx:
            resolve_scene_instances(
                scene,
                resolve_source=lambda path: _source_scene(),
                chain=frozenset({"scenes/room_segment.json"}),
            )
        self.assertIn("Room Instance", str(ctx.exception))

    def test_self_inclusion_is_a_cycle(self) -> None:
        scene = Scene("Self", scene_id="self")
        root = scene.create_entity("Self Instance")
        root.add_component(SceneInstanceComponent("scenes/self.json"))

        with self.assertRaises(SceneInstanceCycleError):
            resolve_scene_instances(
                scene,
                resolve_source=lambda path: scene,
                chain=frozenset({"scenes/self.json"}),
            )

    def test_nested_instance_resolves_through_already_resolved_source(self) -> None:
        # The inner source scene itself contains a resolved instance; the
        # outer resolve treats it as opaque already-resolved content and
        # clones it wholesale (mirrors how Project.load_scene recurses).
        inner_source = _source_scene()

        middle = Scene("Middle", scene_id="middle")
        middle_root = middle.create_entity("Inner Instance")
        middle_root.add_component(SceneInstanceComponent("scenes/room_segment.json"))
        resolve_scene_instances(middle, resolve_source=lambda path: inner_source)

        outer, outer_root_id = _owning_scene_with_instance()
        resolve_scene_instances(outer, resolve_source=lambda path: middle)

        names = {e.name for e in outer.entities}
        self.assertEqual(names, {"Room Instance", "Inner Instance", "Wall", "Door A"})
        inner_instance = outer.find_entity_by_name("Inner Instance")
        assert inner_instance is not None
        self.assertEqual(inner_instance.parent_id, outer_root_id)
        self.assertTrue(outer.is_instance_materialized(inner_instance.entity_id))

    def test_resolving_twice_on_same_scene_does_not_duplicate(self) -> None:
        scene, _root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        names = [e.name for e in scene.entities]
        self.assertEqual(sorted(names), ["Door A", "Room Instance", "Wall"])

    def test_removing_instance_root_forgets_bookkeeping(self) -> None:
        scene, root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())
        wall = scene.find_entity_by_name("Wall")
        assert wall is not None

        scene.remove_entity(root_id, recursive=True)

        self.assertFalse(scene.is_instance_materialized(wall.entity_id))

    def test_duplicated_instance_root_snapshot_is_unlinked_until_re_resolved(self) -> None:
        """Cloning an instance root copies its current materialized children as an
        ordinary structural snapshot -- intended behavior, not a bug: Scene.clone_entity
        has no notion of scene instances. A subsequent resolve pass re-links the clone
        cleanly, replacing the stale snapshot with fresh source-resolved content."""
        scene, root_id = _owning_scene_with_instance()
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        clone = scene.clone_entity(root_id, recursive=True)
        assert clone is not None
        clone_wall = next(
            e for e in scene.entities if e.parent_id == clone.entity_id and e.name == "Wall"
        )
        # Immediately after cloning: a real snapshot entity, but NOT tracked as
        # instance-materialized (clone_entity doesn't know about instances).
        self.assertFalse(scene.is_instance_materialized(clone_wall.entity_id))

        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        # The stale snapshot clone is gone; a fresh materialization replaced it.
        self.assertIsNone(scene.find_entity(clone_wall.entity_id))
        fresh_subtree = [
            e for e in scene.walk_hierarchy(clone.entity_id) if e.entity_id != clone.entity_id
        ]
        self.assertEqual({e.name for e in fresh_subtree}, {"Wall", "Door A"})
        for descendant in fresh_subtree:
            self.assertTrue(scene.is_instance_materialized(descendant.entity_id))

    def test_reopen_round_trip_preserves_root_identity_and_regenerates_children(self) -> None:
        scene, root_id = _owning_scene_with_instance(overrides={"Door A": {"open_speed": 3.0}})
        resolve_scene_instances(scene, resolve_source=lambda path: _source_scene())

        persisted = scene.to_dict(include_instance_content=False)
        reloaded = Scene.from_dict(persisted)
        resolve_scene_instances(reloaded, resolve_source=lambda path: _source_scene())

        self.assertIsNotNone(reloaded.find_entity(root_id))
        door = reloaded.find_entity_by_name("Door A")
        assert door is not None
        script = door.get_component(ScriptComponent)
        assert script is not None
        self.assertEqual(script.exposed_values["open_speed"], 3.0)


if __name__ == "__main__":
    unittest.main()
