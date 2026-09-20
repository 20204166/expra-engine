"""Tests for Scene."""

import json
import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene


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

    def test_from_dict_with_unknown_component_type_skips(self) -> None:
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
        self.assertEqual(len(entity.components), 0)


if __name__ == "__main__":
    unittest.main()
