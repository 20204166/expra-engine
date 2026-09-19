"""Tests for Entity tag support and Scene hierarchy/query operations.

Edge cases adapted from ppb/tests/test_gom.py (PursuedPyBear, Artistic
License 2.0). Translated to Expra's Entity/Scene model.

Tests cover:
  - Entity tags: add, remove, has, frozenset immutability
  - Tag serialization round-trip
  - Scene.get_entities_by_tag
  - Scene.get_entities_by_component
  - Scene.get_entities() with combined tag+component filter
  - Scene.get_entities() with no args raises TypeError
  - Hierarchy: children_of, roots, set_entity_parent
  - Hierarchy: self-parent raises ValueError
  - Hierarchy: cycle detection raises ValueError
  - Hierarchy: walk_hierarchy DFS traversal
  - Hierarchy serialization round-trip (parent_id preserved)
"""

import json
import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene


class TestEntityTags(unittest.TestCase):
    def test_default_tags_empty(self) -> None:
        e = Entity("A")
        self.assertEqual(len(e.tags), 0)

    def test_add_tag(self) -> None:
        e = Entity("A")
        e.add_tag("enemy")
        self.assertIn("enemy", e.tags)

    def test_has_tag(self) -> None:
        e = Entity("A")
        e.add_tag("player")
        self.assertTrue(e.has_tag("player"))
        self.assertFalse(e.has_tag("enemy"))

    def test_remove_tag(self) -> None:
        e = Entity("A")
        e.add_tag("static")
        e.remove_tag("static")
        self.assertFalse(e.has_tag("static"))

    def test_remove_absent_tag_is_noop(self) -> None:
        e = Entity("A")
        e.remove_tag("nonexistent")  # must not raise

    def test_tags_property_is_frozenset(self) -> None:
        e = Entity("A")
        e.add_tag("x")
        t = e.tags
        self.assertIsInstance(t, frozenset)
        # Cannot mutate the frozenset
        with self.assertRaises(AttributeError):
            t.add("y")  # type: ignore[attr-defined]

    def test_multiple_tags(self) -> None:
        e = Entity("A")
        e.add_tag("red")
        e.add_tag("blue")
        self.assertIn("red", e.tags)
        self.assertIn("blue", e.tags)
        self.assertEqual(len(e.tags), 2)

    def test_tag_round_trip(self) -> None:
        e = Entity("A", entity_id="e-1")
        e.add_tag("boss")
        e.add_tag("static")
        data = e.to_dict()
        loaded = Entity.from_dict(data)
        self.assertIn("boss", loaded.tags)
        self.assertIn("static", loaded.tags)

    def test_tag_round_trip_empty(self) -> None:
        e = Entity("B", entity_id="e-2")
        data = e.to_dict()
        loaded = Entity.from_dict(data)
        self.assertEqual(len(loaded.tags), 0)

    def test_tags_in_to_dict_sorted(self) -> None:
        e = Entity("C", entity_id="e-3")
        e.add_tag("z")
        e.add_tag("a")
        data = e.to_dict()
        self.assertEqual(data["tags"], ["a", "z"])

    def test_from_dict_without_tags_key_ok(self) -> None:
        """Legacy dicts without 'tags' load without error."""
        data = {
            "entity_id": "e-4",
            "name": "Old",
            "enabled": True,
            "parent_id": None,
            "components": [],
        }
        e = Entity.from_dict(data)
        self.assertEqual(len(e.tags), 0)


class TestSceneTagQuery(unittest.TestCase):
    def setUp(self) -> None:
        self.scene = Scene("Test")
        self.e1 = self.scene.create_entity("Enemy1")
        self.e1.add_tag("enemy")
        self.e2 = self.scene.create_entity("Enemy2")
        self.e2.add_tag("enemy")
        self.e2.add_tag("boss")
        self.e3 = self.scene.create_entity("Player")
        self.e3.add_tag("player")

    def test_get_by_tag_returns_matching(self) -> None:
        enemies = self.scene.get_entities_by_tag("enemy")
        self.assertIn(self.e1, enemies)
        self.assertIn(self.e2, enemies)
        self.assertEqual(len(enemies), 2)

    def test_get_by_tag_absent(self) -> None:
        result = self.scene.get_entities_by_tag("does-not-exist")
        self.assertEqual(len(result), 0)

    def test_get_by_tag_single(self) -> None:
        bosses = self.scene.get_entities_by_tag("boss")
        self.assertEqual(len(bosses), 1)
        self.assertIn(self.e2, bosses)


class TestSceneComponentQuery(unittest.TestCase):
    def setUp(self) -> None:
        self.scene = Scene("Test")
        self.with_transform = self.scene.create_entity("Sprite")
        self.with_transform.add_component(TransformComponent(x=1.0))
        self.without = self.scene.create_entity("Audio")

    def test_get_by_component_returns_matching(self) -> None:
        result = self.scene.get_entities_by_component(TransformComponent)
        self.assertIn(self.with_transform, result)
        self.assertNotIn(self.without, result)

    def test_get_by_component_empty(self) -> None:
        scene = Scene("Empty")
        result = scene.get_entities_by_component(TransformComponent)
        self.assertEqual(len(result), 0)


class TestSceneGetEntities(unittest.TestCase):
    def setUp(self) -> None:
        self.scene = Scene("Test")
        self.e1 = self.scene.create_entity("Bullet")
        self.e1.add_tag("projectile")
        self.e1.add_component(TransformComponent())
        self.e2 = self.scene.create_entity("BigBullet")
        self.e2.add_tag("projectile")
        self.e2.add_tag("heavy")
        self.e2.add_component(TransformComponent())
        self.e3 = self.scene.create_entity("Sound")
        self.e3.add_tag("projectile")  # tag but no transform

    def test_no_args_raises(self) -> None:
        with self.assertRaises(TypeError):
            self.scene.get_entities()  # type: ignore[call-arg]

    def test_tag_only(self) -> None:
        result = self.scene.get_entities(tag="projectile")
        self.assertIn(self.e1, result)
        self.assertIn(self.e2, result)
        self.assertIn(self.e3, result)
        self.assertEqual(len(result), 3)

    def test_component_only(self) -> None:
        result = self.scene.get_entities(component=TransformComponent)
        self.assertIn(self.e1, result)
        self.assertIn(self.e2, result)
        self.assertNotIn(self.e3, result)

    def test_tag_and_component_intersection(self) -> None:
        result = self.scene.get_entities(tag="projectile", component=TransformComponent)
        self.assertIn(self.e1, result)
        self.assertIn(self.e2, result)
        self.assertNotIn(self.e3, result)
        self.assertEqual(len(result), 2)

    def test_tag_and_component_no_match(self) -> None:
        result = self.scene.get_entities(tag="heavy", component=TransformComponent)
        self.assertEqual(len(result), 1)
        self.assertIn(self.e2, result)


class TestSceneHierarchy(unittest.TestCase):
    def _make_tree(self) -> tuple[Scene, Entity, Entity, Entity, Entity]:
        """
        root1 (parent=None)
          └── child1 (parent=root1)
               └── grandchild (parent=child1)
        root2 (parent=None)
        """
        scene = Scene("H")
        root1 = scene.create_entity("Root1")
        root2 = scene.create_entity("Root2")
        child1 = scene.create_entity("Child1")
        grandchild = scene.create_entity("Grandchild")
        scene.set_entity_parent(child1.entity_id, root1.entity_id)
        scene.set_entity_parent(grandchild.entity_id, child1.entity_id)
        return scene, root1, root2, child1, grandchild

    def test_roots_returns_parentless(self) -> None:
        scene, root1, root2, child1, grandchild = self._make_tree()
        roots = scene.roots()
        self.assertIn(root1, roots)
        self.assertIn(root2, roots)
        self.assertNotIn(child1, roots)
        self.assertNotIn(grandchild, roots)

    def test_children_of(self) -> None:
        scene, root1, _root2, child1, grandchild = self._make_tree()
        ch = scene.children_of(root1.entity_id)
        self.assertIn(child1, ch)
        self.assertNotIn(grandchild, ch)

    def test_children_of_leaf(self) -> None:
        scene, _root1, _root2, _child1, grandchild = self._make_tree()
        ch = scene.children_of(grandchild.entity_id)
        self.assertEqual(len(ch), 0)

    def test_self_parent_raises(self) -> None:
        scene = Scene("T")
        scene.create_entity("E", entity_id="e-1")
        with self.assertRaises(ValueError):
            scene.set_entity_parent("e-1", "e-1")

    def test_foreign_entity_raises(self) -> None:
        scene = Scene("T")
        with self.assertRaises(ValueError):
            scene.set_entity_parent("nonexistent", None)

    def test_foreign_parent_raises(self) -> None:
        scene = Scene("T")
        scene.create_entity("E", entity_id="e-1")
        with self.assertRaises(ValueError):
            scene.set_entity_parent("e-1", "no-such-parent")

    def test_cycle_direct_raises(self) -> None:
        scene = Scene("T")
        scene.create_entity("A", entity_id="a")
        scene.create_entity("B", entity_id="b")
        scene.set_entity_parent("b", "a")
        with self.assertRaises(ValueError):
            scene.set_entity_parent("a", "b")  # would create a ↔ b cycle

    def test_cycle_indirect_raises(self) -> None:
        scene = Scene("T")
        scene.create_entity("A", entity_id="a")
        scene.create_entity("B", entity_id="b")
        scene.create_entity("C", entity_id="c")
        scene.set_entity_parent("b", "a")
        scene.set_entity_parent("c", "b")
        with self.assertRaises(ValueError):
            scene.set_entity_parent("a", "c")  # a → c → b → a cycle

    def test_reparent_removes_from_old(self) -> None:
        scene, root1, root2, child1, _grandchild = self._make_tree()
        scene.set_entity_parent(child1.entity_id, root2.entity_id)
        self.assertEqual(child1.parent_id, root2.entity_id)
        self.assertNotIn(child1, scene.children_of(root1.entity_id))

    def test_clear_parent(self) -> None:
        scene, _root1, _root2, child1, _grandchild = self._make_tree()
        scene.set_entity_parent(child1.entity_id, None)
        self.assertIsNone(child1.parent_id)
        self.assertIn(child1, scene.roots())


class TestSceneWalkHierarchy(unittest.TestCase):
    def test_walk_full_tree(self) -> None:
        scene = Scene("T")
        root = scene.create_entity("Root")
        child = scene.create_entity("Child")
        grandchild = scene.create_entity("GC")
        scene.set_entity_parent(child.entity_id, root.entity_id)
        scene.set_entity_parent(grandchild.entity_id, child.entity_id)

        result = scene.walk_hierarchy()
        self.assertIn(root, result)
        self.assertIn(child, result)
        self.assertIn(grandchild, result)

    def test_walk_subtree(self) -> None:
        scene = Scene("T")
        root = scene.create_entity("Root")
        child = scene.create_entity("Child")
        scene.set_entity_parent(child.entity_id, root.entity_id)
        other_root = scene.create_entity("OtherRoot")

        result = scene.walk_hierarchy(root.entity_id)
        self.assertIn(root, result)
        self.assertIn(child, result)
        self.assertNotIn(other_root, result)

    def test_walk_nonexistent_root_empty(self) -> None:
        scene = Scene("T")
        result = scene.walk_hierarchy("no-such-id")
        self.assertEqual(result, [])

    def test_walk_parent_before_children(self) -> None:
        scene = Scene("T")
        root = scene.create_entity("Root")
        child1 = scene.create_entity("C1")
        child2 = scene.create_entity("C2")
        scene.set_entity_parent(child1.entity_id, root.entity_id)
        scene.set_entity_parent(child2.entity_id, root.entity_id)

        result = scene.walk_hierarchy()
        root_idx = result.index(root)
        c1_idx = result.index(child1)
        c2_idx = result.index(child2)
        self.assertLess(root_idx, c1_idx)
        self.assertLess(root_idx, c2_idx)

    def test_walk_empty_scene(self) -> None:
        scene = Scene("Empty")
        result = scene.walk_hierarchy()
        self.assertEqual(result, [])


class TestHierarchySerializationRoundTrip(unittest.TestCase):
    def test_parent_ids_survive_json(self) -> None:
        scene = Scene("S")
        scene.create_entity("Parent", entity_id="p-1")
        scene.create_entity("Child", entity_id="c-1")
        scene.set_entity_parent("c-1", "p-1")

        data = json.loads(json.dumps(scene.to_dict()))
        loaded = Scene.from_dict(data)

        loaded_child = loaded.find_entity("c-1")
        self.assertIsNotNone(loaded_child)
        assert loaded_child is not None
        self.assertEqual(loaded_child.parent_id, "p-1")

    def test_tags_survive_json(self) -> None:
        scene = Scene("S")
        e = scene.create_entity("E", entity_id="e-1")
        e.add_tag("static")
        e.add_tag("collidable")

        data = json.loads(json.dumps(scene.to_dict()))
        loaded = Scene.from_dict(data)
        loaded_e = loaded.find_entity("e-1")
        assert loaded_e is not None
        self.assertIn("static", loaded_e.tags)
        self.assertIn("collidable", loaded_e.tags)


if __name__ == "__main__":
    unittest.main()
