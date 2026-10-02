"""Tests for Scene."""

import json
import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene, SceneCamera
from expra_engine.core.scene.camera import Camera2D
from expra_engine.runtime.behaviour import Behaviour
from expra_engine.runtime.visual_components import PrimitiveComponent


class _AppendOnlyProbeList(list):
    def __contains__(self, _item) -> bool:
        raise AssertionError("component index append should not scan membership")


class TestSceneBasics(unittest.TestCase):
    def test_entities_by_layer_sorted(self) -> None:
        scene = Scene("test")
        background = Entity(name="bg", layer=0)
        foreground = Entity(name="fg", layer=2)
        middle = Entity(name="mid", layer=1)
        for entity in (background, foreground, middle):
            scene.add_entity(entity)

        ordered = scene.entities_by_layer()

        self.assertEqual([entity.name for entity in ordered], ["bg", "mid", "fg"])

    def test_create_entity(self) -> None:
        scene = Scene("Test")
        entity = scene.create_entity("Player")
        self.assertEqual(len(scene.entities), 1)
        self.assertEqual(entity.name, "Player")

    def test_iter_entities_streams_in_scene_order(self) -> None:
        scene = Scene("Test")
        entities = [scene.create_entity(f"entity-{index}") for index in range(3)]

        self.assertEqual(tuple(scene.iter_entities()), tuple(entities))

    def test_component_index_tracks_mutations_and_preserves_scene_order(self) -> None:
        scene = Scene("Test")
        older = scene.create_entity("older")
        newer = scene.create_entity("newer")
        newer.add_component(TransformComponent())
        older.add_component(TransformComponent())

        self.assertEqual(
            tuple(scene.iter_entities_by_component(TransformComponent)), (older, newer)
        )
        self.assertEqual(scene.get_entities_by_component(TransformComponent), (older, newer))

        older_transform = older.get_component(TransformComponent)
        assert older_transform is not None
        older.remove_component(older_transform)
        self.assertEqual(tuple(scene.iter_entities_by_component(TransformComponent)), (newer,))
        self.assertTrue(scene.remove_entity(newer.entity_id))
        self.assertEqual(tuple(scene.iter_entities_by_component(TransformComponent)), ())

        prepopulated = Entity("prepopulated")
        prepopulated.add_component(TransformComponent())
        scene.add_entity(prepopulated)
        self.assertEqual(tuple(scene.iter_entities_by_component(TransformComponent)), (prepopulated,))

    def test_component_index_appends_new_scene_entities_without_list_membership_scans(self) -> None:
        scene = Scene("Append-only component index")
        first = scene.create_entity("first")
        first.add_component(TransformComponent())
        scene._component_entities[TransformComponent] = _AppendOnlyProbeList(
            scene._component_entities[TransformComponent]
        )
        second = Entity("second")
        second.add_component(TransformComponent())

        scene.add_entity(second)

        self.assertEqual(
            tuple(scene.iter_entities_by_component(TransformComponent)), (first, second)
        )

    def test_runtime_event_targets_follow_behaviour_attachment(self) -> None:
        scene = Scene("Test")
        entity = scene.create_entity("listener")
        self.assertEqual(scene._entities_for_event("on_update"), ())

        class Listener(Behaviour):
            pass

        behaviour = Listener()
        entity.add_behaviour(behaviour, runtime_factory=Listener)
        self.assertEqual(scene._entities_for_event("on_update"), (entity,))
        self.assertEqual(scene._entities_for_event("on_idle"), (entity,))

        self.assertTrue(entity.remove_behaviour(behaviour))
        self.assertEqual(scene._entities_for_event("on_update"), ())
        self.assertEqual(scene._entities_for_event("on_idle"), ())

    def test_runtime_event_targets_include_custom_entity_handlers(self) -> None:
        class Listener(Entity):
            def on_update(self, event, signal) -> None:
                pass

        scene = Scene("Test")
        listener = Listener("custom")
        scene.add_entity(listener)

        self.assertEqual(scene._entities_for_event("on_update"), (listener,))

    def test_component_and_entity_render_edits_mark_the_scene_dirty(self) -> None:
        scene = Scene("Test")
        entity = scene.create_entity("shape")
        primitive = PrimitiveComponent("rectangle")
        entity.add_component(primitive)
        self.assertEqual(scene._take_render_entity_ids(), (entity.entity_id,))

        primitive.width = 4.0
        entity.enabled = False
        self.assertEqual(scene._take_render_entity_ids(), (entity.entity_id,))

    def test_find_entity(self) -> None:
        scene = Scene("Test")
        e = scene.create_entity("Camera")
        found = scene.find_entity(e.entity_id)
        self.assertIs(found, e)

    def test_find_entity_missing(self) -> None:
        scene = Scene("Test")
        self.assertIsNone(scene.find_entity("nonexistent-id"))

    def test_remove_entity(self) -> None:
        scene = Scene("Test")
        e = scene.create_entity("Enemy")
        result = scene.remove_entity(e.entity_id)
        self.assertTrue(result)
        self.assertEqual(len(scene.entities), 0)

    def test_remove_entity_missing(self) -> None:
        scene = Scene("Test")
        self.assertFalse(scene.remove_entity("no-such-id"))

    def test_add_entity(self) -> None:
        scene = Scene("Test")
        entity = Entity("Projectile", entity_id="fixed-id")
        scene.add_entity(entity)
        self.assertIs(scene.find_entity("fixed-id"), entity)

    def test_find_entity_by_name(self) -> None:
        scene = Scene("Test")
        scene.create_entity("Boss")
        found = scene.find_entity_by_name("Boss")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.name, "Boss")


class TestSceneSerialization(unittest.TestCase):
    def test_scene_camera_is_owned_object_with_legacy_mapping_access(self) -> None:
        scene = Scene("Camera", camera={"target_entity_id": "player"})

        self.assertIsInstance(scene.camera, SceneCamera)
        self.assertEqual(scene.camera.target_entity_id, "player")
        self.assertEqual(scene.camera["target_entity_id"], "player")

    def test_camera_settings_round_trip_without_affecting_legacy_scenes(self) -> None:
        scene = Scene("Camera Level")
        camera = Camera2D(position=(3.0, 4.0), target_width=12.0, viewport=(800, 600))
        camera.zoom = 2.0
        camera.rotation = 0.25
        scene.camera = camera.to_dict()

        loaded = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))

        self.assertEqual(loaded.camera["position"], [3.0, 4.0])
        self.assertEqual(loaded.camera["zoom"], 2.0)
        self.assertEqual(loaded.camera["rotation"], 0.25)

    def test_legacy_scene_without_camera_keeps_original_shape(self) -> None:
        loaded = Scene.from_dict({"scene_id": "s", "name": "Legacy", "entities": []})

        self.assertNotIn("camera", loaded.to_dict())

    def test_round_trip_preserves_ids(self) -> None:
        scene = Scene("Level 1", scene_id="s-001")
        e = scene.create_entity("Hero", entity_id="e-001")
        e.add_component(TransformComponent(x=10.0, y=-5.0, rotation=45.0))

        data = scene.to_dict()
        loaded = Scene.from_dict(data)

        self.assertEqual(loaded.scene_id, "s-001")
        self.assertEqual(loaded.name, "Level 1")
        self.assertEqual(len(loaded.entities), 1)

        hero = loaded.find_entity("e-001")
        self.assertIsNotNone(hero)
        assert hero is not None
        self.assertEqual(hero.name, "Hero")

        transform = hero.get_component(TransformComponent)
        self.assertIsNotNone(transform)
        assert transform is not None
        self.assertAlmostEqual(transform.x, 10.0)
        self.assertAlmostEqual(transform.y, -5.0)
        self.assertAlmostEqual(transform.rotation, 45.0)

    def test_round_trip_through_json(self) -> None:
        scene = Scene("Stage 1", scene_id="stage-1")
        scene.create_entity("Player", entity_id="p-1")

        json_str = json.dumps(scene.to_dict())
        loaded = Scene.from_dict(json.loads(json_str))

        self.assertEqual(loaded.scene_id, "stage-1")
        self.assertIsNotNone(loaded.find_entity("p-1"))

    def test_ids_survive_multiple_round_trips(self) -> None:
        scene = Scene("Multi", scene_id="m-1")
        scene.create_entity("Object", entity_id="o-1")

        for _ in range(3):
            scene = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))

        self.assertEqual(scene.scene_id, "m-1")
        self.assertIsNotNone(scene.find_entity("o-1"))

    def test_from_dict_with_unknown_component_type_preserves_payload(self) -> None:
        data = {
            "scene_id": "s-1",
            "name": "Test",
            "entities": [
                {
                    "entity_id": "e-1",
                    "name": "Obj",
                    "enabled": True,
                    "parent_id": None,
                    "components": [{"type": "unknown_future_type"}],
                }
            ],
        }
        scene = Scene.from_dict(data)
        entity = scene.find_entity("e-1")
        self.assertIsNotNone(entity)
        assert entity is not None
        self.assertEqual(entity.to_dict()["components"], [{"type": "unknown_future_type"}])


class TestSceneWorldPose(unittest.TestCase):
    def test_missing_entity_raises(self) -> None:
        scene = Scene("test")
        with self.assertRaises(KeyError):
            scene.world_pose("no-such-id")

    def test_no_transform_is_identity(self) -> None:
        scene = Scene("test")
        e = scene.create_entity("e")
        self.assertEqual(scene.world_pose(e.entity_id), (0.0, 0.0, 0.0))

    def test_disabled_transform_is_identity(self) -> None:
        scene = Scene("test")
        e = scene.create_entity("e")
        e.add_component(TransformComponent(x=5.0, enabled=False))
        self.assertEqual(scene.world_pose(e.entity_id), (0.0, 0.0, 0.0))

    def test_non_finite_transform_raises(self) -> None:
        scene = Scene("test")
        e = scene.create_entity("e")
        e.add_component(TransformComponent(x=float("inf")))
        with self.assertRaises(ValueError):
            scene.world_pose(e.entity_id)


if __name__ == "__main__":
    unittest.main()
