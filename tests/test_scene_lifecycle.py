"""Edge/regression tests for Scene entity lifecycle: recursive delete and clone."""

import unittest

from expra_engine.core.component import Component
from expra_engine.core.scene import Scene


class DummyComponent(Component):
    def __init__(self, value: int) -> None:
        self.value = value

    def to_dict(self):
        return {"type": "DummyComponent", "value": self.value}

    @classmethod
    def from_dict(cls, data):
        return cls(data["value"])


class RecursiveDeleteTests(unittest.TestCase):
    def _tree(self) -> tuple[Scene, str, str, str]:
        s = Scene("test")
        parent = s.create_entity("parent")
        child = s.create_entity("child", parent_id=parent.entity_id)
        grandchild = s.create_entity("grandchild", parent_id=child.entity_id)
        return s, parent.entity_id, child.entity_id, grandchild.entity_id

    def test_leaf_delete(self) -> None:
        s, pid, cid, gcid = self._tree()
        result = s.remove_entity(gcid, recursive=True)
        self.assertTrue(result)
        self.assertIsNotNone(s.find_entity(pid))
        self.assertIsNotNone(s.find_entity(cid))
        self.assertIsNone(s.find_entity(gcid))

    def test_parent_recursive_deletes_all_descendants(self) -> None:
        s, pid, cid, gcid = self._tree()
        s.remove_entity(pid, recursive=True)
        self.assertIsNone(s.find_entity(pid))
        self.assertIsNone(s.find_entity(cid))
        self.assertIsNone(s.find_entity(gcid))

    def test_no_dangling_parent_ids_after_subtree_delete(self) -> None:
        s, pid, cid, gcid = self._tree()
        sibling = s.create_entity("sibling")
        s.remove_entity(pid, recursive=True)
        # Sibling (not in subtree) must still be present
        self.assertIsNotNone(s.find_entity(sibling.entity_id))
        # All deleted entities must be gone
        for eid in (pid, cid, gcid):
            self.assertIsNone(s.find_entity(eid))
        # Scene list is internally consistent
        remaining_ids = {e.entity_id for e in s.entities}
        for e in s.entities:
            if e.parent_id is not None:
                self.assertIn(e.parent_id, remaining_ids)

    def test_nonexistent_id_returns_false(self) -> None:
        s = Scene("test")
        self.assertFalse(s.remove_entity("nope", recursive=True))

    def test_repeated_delete_returns_false(self) -> None:
        s = Scene("test")
        e = s.create_entity("x")
        eid = e.entity_id
        s.remove_entity(eid, recursive=True)
        self.assertFalse(s.remove_entity(eid, recursive=True))

    def test_flat_remove_does_not_cascade(self) -> None:
        s, pid, cid, _gcid = self._tree()
        s.remove_entity(pid, recursive=False)
        # Child still exists but now has a dangling parent_id (flat remove)
        self.assertIsNone(s.find_entity(pid))
        self.assertIsNotNone(s.find_entity(cid))


class CloneEntityTests(unittest.TestCase):
    def test_clone_returns_new_entity(self) -> None:
        s = Scene("test")
        src = s.create_entity("hero")
        clone = s.clone_entity(src.entity_id)
        self.assertIsNotNone(clone)
        self.assertNotEqual(clone.entity_id, src.entity_id)  # type: ignore[union-attr]
        self.assertEqual(clone.name, "hero")  # type: ignore[union-attr]

    def test_clone_nonexistent_returns_none(self) -> None:
        s = Scene("test")
        self.assertIsNone(s.clone_entity("not-there"))

    def test_clone_copies_components_not_sharing(self) -> None:
        s = Scene("test")
        src = s.create_entity("e")
        src.add_component(DummyComponent(42))
        clone = s.clone_entity(src.entity_id)
        assert clone is not None
        orig_comp = src.get_component(DummyComponent)
        clone_comp = clone.get_component(DummyComponent)
        self.assertIsNotNone(clone_comp)
        self.assertIsNot(orig_comp, clone_comp)
        # Mutating clone component must not affect original
        clone_comp.value = 99  # type: ignore[union-attr]
        self.assertEqual(orig_comp.value, 42)  # type: ignore[union-attr]

    def test_clone_copies_tags(self) -> None:
        s = Scene("test")
        src = s.create_entity("e")
        src.add_tag("enemy")
        src.add_tag("active")
        clone = s.clone_entity(src.entity_id)
        assert clone is not None
        self.assertTrue(clone.has_tag("enemy"))
        self.assertTrue(clone.has_tag("active"))

    def test_clone_recursive_remaps_parent_ids(self) -> None:
        s = Scene("test")
        parent = s.create_entity("parent")
        child = s.create_entity("child", parent_id=parent.entity_id)
        cloned_parent = s.clone_entity(parent.entity_id, recursive=True)
        assert cloned_parent is not None
        # Find the cloned child in the scene
        cloned_children = s.children_of(cloned_parent.entity_id)
        self.assertEqual(len(cloned_children), 1)
        cloned_child = cloned_children[0]
        self.assertNotEqual(cloned_child.entity_id, child.entity_id)
        self.assertEqual(cloned_child.parent_id, cloned_parent.entity_id)

    def test_clone_ids_all_differ_from_originals(self) -> None:
        s = Scene("test")
        root = s.create_entity("root")
        c1 = s.create_entity("c1", parent_id=root.entity_id)
        c2 = s.create_entity("c2", parent_id=root.entity_id)
        original_ids = {root.entity_id, c1.entity_id, c2.entity_id}
        s.clone_entity(root.entity_id, recursive=True)
        new_entities = [e for e in s.entities if e.entity_id not in original_ids]
        new_ids = {e.entity_id for e in new_entities}
        self.assertTrue(original_ids.isdisjoint(new_ids))

    def test_clone_does_not_mutate_source(self) -> None:
        s = Scene("test")
        src = s.create_entity("hero")
        src.add_component(DummyComponent(1))
        orig_id = src.entity_id
        orig_count = len(src.components)
        s.clone_entity(orig_id)
        self.assertEqual(src.entity_id, orig_id)
        self.assertEqual(len(src.components), orig_count)

    def test_non_recursive_clone_shallow(self) -> None:
        s = Scene("test")
        parent = s.create_entity("parent")
        _child = s.create_entity("child", parent_id=parent.entity_id)
        clone = s.clone_entity(parent.entity_id, recursive=False)
        assert clone is not None
        self.assertNotEqual(clone.entity_id, parent.entity_id)
        # Only root was cloned, children of clone should be empty
        self.assertEqual(len(s.children_of(clone.entity_id)), 0)


if __name__ == "__main__":
    unittest.main()
