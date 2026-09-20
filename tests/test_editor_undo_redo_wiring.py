"""Integration tests for editor commands and the undo/redo stack."""

from __future__ import annotations

import unittest

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import (
    CommandStack,
    DeleteEntityCommand,
    RenameEntityCommand,
)


class CommandStackUndoRedoWiringTests(unittest.TestCase):
    """Verify command execution, undo, redo, and branch invalidation."""

    def setUp(self) -> None:
        self.scene = Scene("Test")
        self.entity = Entity(name="Bob")
        self.scene.add_entity(self.entity)
        self.stack = CommandStack()

    def test_rename_push_execute_undo_cycle(self) -> None:
        command = RenameEntityCommand(self.entity, "Bob", "Alice")

        self.stack.push(command)

        self.assertEqual(self.entity.name, "Alice")
        self.stack.undo()
        self.assertEqual(self.entity.name, "Bob")

    def test_delete_push_execute_undo_restores_entity(self) -> None:
        command = DeleteEntityCommand(self.scene, self.entity)

        self.stack.push(command)

        self.assertIsNone(self.scene.find_entity(self.entity.entity_id))
        self.stack.undo()
        restored = self.scene.find_entity(self.entity.entity_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.name, "Bob")

    def test_redo_after_delete_undo_deletes_again(self) -> None:
        self.stack.push(DeleteEntityCommand(self.scene, self.entity))

        self.stack.undo()
        self.stack.redo()

        self.assertIsNone(self.scene.find_entity(self.entity.entity_id))

    def test_push_after_undo_discards_redo_branch(self) -> None:
        first = RenameEntityCommand(self.entity, "Bob", "Alice")
        replacement = RenameEntityCommand(self.entity, "Bob", "Charlie")

        self.stack.push(first)
        self.stack.undo()
        self.stack.push(replacement)

        self.assertFalse(self.stack.can_redo)
        self.assertEqual(self.entity.name, "Charlie")

    def test_undo_redo_enabled_state_tracks_stack(self) -> None:
        self.assertFalse(self.stack.can_undo)
        self.assertFalse(self.stack.can_redo)

        self.stack.push(RenameEntityCommand(self.entity, "Bob", "Alice"))
        self.assertTrue(self.stack.can_undo)
        self.assertFalse(self.stack.can_redo)

        self.stack.undo()
        self.assertFalse(self.stack.can_undo)
        self.assertTrue(self.stack.can_redo)


if __name__ == "__main__":
    unittest.main()
