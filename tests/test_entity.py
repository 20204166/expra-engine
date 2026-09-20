"""Tests for Entity and Component."""

import unittest
from dataclasses import dataclass

from expra_engine.core.component import (
    Component,
    TransformComponent,
    component_from_dict,
    register_component_type,
)
from expra_engine.core.entity import Entity


class TestEntityBasics(unittest.TestCase):
    def test_default_layer_is_zero(self) -> None:
        entity = Entity(name="Background")

        self.assertEqual(entity.layer, 0)

    def test_entity_has_stable_id(self) -> None:
        e = Entity("Player", entity_id="p-001")
        self.assertEqual(e.entity_id, "p-001")

    def test_entity_auto_id_generated(self) -> None:
        e = Entity("Enemy")
        self.assertIsNotNone(e.entity_id)
        self.assertGreater(len(e.entity_id), 0)

    def test_add_component(self) -> None:
        e = Entity("Hero")
        t = TransformComponent()
        e.add_component(t)
        self.assertIn(t, e.components)

    def test_get_component(self) -> None:
        e = Entity("Hero")
        t = TransformComponent(x=5.0)
        e.add_component(t)
        found = e.get_component(TransformComponent)
        self.assertIs(found, t)

    def test_get_component_missing_returns_none(self) -> None:
        e = Entity("Empty")
        self.assertIsNone(e.get_component(TransformComponent))

    def test_remove_component(self) -> None:
        e = Entity("Hero")
        t = TransformComponent()
        e.add_component(t)
        result = e.remove_component(t)
        self.assertTrue(result)
        self.assertNotIn(t, e.components)

    def test_remove_component_not_present(self) -> None:
        e = Entity("Hero")
        t = TransformComponent()
        result = e.remove_component(t)
        self.assertFalse(result)


class TestEntitySerialization(unittest.TestCase):
    def test_round_trip(self) -> None:
        e = Entity("Archer", entity_id="a-1", enabled=True)
        t = TransformComponent(x=3.0, y=4.0, rotation=90.0, scale_x=2.0, scale_y=2.0)
        e.add_component(t)

        data = e.to_dict()
        loaded = Entity.from_dict(data)

        self.assertEqual(loaded.entity_id, "a-1")
        self.assertEqual(loaded.name, "Archer")
        self.assertTrue(loaded.enabled)

        lt = loaded.get_component(TransformComponent)
        self.assertIsNotNone(lt)
        assert lt is not None
        self.assertAlmostEqual(lt.x, 3.0)
        self.assertAlmostEqual(lt.y, 4.0)
        self.assertAlmostEqual(lt.rotation, 90.0)
        self.assertAlmostEqual(lt.scale_x, 2.0)

    def test_enabled_flag_preserved(self) -> None:
        e = Entity("Ghost", entity_id="g-1", enabled=False)
        loaded = Entity.from_dict(e.to_dict())
        self.assertFalse(loaded.enabled)

    def test_parent_id_preserved(self) -> None:
        e = Entity("Child", entity_id="c-1", parent_id="parent-id")
        loaded = Entity.from_dict(e.to_dict())
        self.assertEqual(loaded.parent_id, "parent-id")

    def test_layer_round_trips_to_dict(self) -> None:
        entity = Entity("Foreground", entity_id="f-1", layer=5)

        loaded = Entity.from_dict(entity.to_dict())

        self.assertEqual(loaded.layer, 5)


class TestTransformComponent(unittest.TestCase):
    def test_defaults(self) -> None:
        t = TransformComponent()
        self.assertAlmostEqual(t.x, 0.0)
        self.assertAlmostEqual(t.y, 0.0)
        self.assertAlmostEqual(t.rotation, 0.0)
        self.assertAlmostEqual(t.scale_x, 1.0)
        self.assertAlmostEqual(t.scale_y, 1.0)
        self.assertTrue(t.enabled)

    def test_custom_values(self) -> None:
        t = TransformComponent(x=10.0, y=-5.0, rotation=180.0, scale_x=0.5, scale_y=2.0)
        self.assertAlmostEqual(t.x, 10.0)
        self.assertAlmostEqual(t.y, -5.0)
        self.assertAlmostEqual(t.rotation, 180.0)

    def test_round_trip(self) -> None:
        t = TransformComponent(x=1.5, y=2.5, rotation=30.0)
        loaded = TransformComponent.from_dict(t.to_dict())
        self.assertAlmostEqual(loaded.x, 1.5)
        self.assertAlmostEqual(loaded.y, 2.5)
        self.assertAlmostEqual(loaded.rotation, 30.0)

    def test_component_type(self) -> None:
        t = TransformComponent()
        self.assertEqual(t.component_type, "transform")


class ComponentRegistryTests(unittest.TestCase):
    def test_component_from_dict_known_type(self) -> None:
        component = component_from_dict({"type": "transform", "x": 1.0, "y": 2.0, "rotation": 0.0})

        self.assertIsInstance(component, TransformComponent)
        self.assertAlmostEqual(component.x, 1.0)

    def test_component_from_dict_unknown_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            component_from_dict({"type": "__nonexistent__"})

    def test_register_custom_type(self) -> None:
        @dataclass
        class TagComponent(Component):
            tag: str = ""

            def to_dict(self) -> dict[str, str]:
                return {"type": "test_tag", "tag": self.tag}

            @classmethod
            def from_dict(cls, data: dict[str, object]) -> "TagComponent":
                return cls(tag=str(data.get("tag", "")))

        register_component_type("test_tag", TagComponent)

        component = component_from_dict({"type": "test_tag", "tag": "player"})

        self.assertIsInstance(component, TagComponent)
        self.assertEqual(component.tag, "player")


if __name__ == "__main__":
    unittest.main()
