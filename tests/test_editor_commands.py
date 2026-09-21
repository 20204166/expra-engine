"""Tests for the editor undo/redo command model."""

import unittest

from expra_engine.core.entity import Entity
from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import (
    Command,
    CommandStack,
    DeleteEntityCommand,
    AddComponentCommand,
    RemoveComponentCommand,
    RenameEntityCommand,
    SetComponentPropertyCommand,
)


class SimpleCommand(Command):
    """Test double that records execute/undo call counts."""

    def __init__(self, label: str, log: list) -> None:
        self._label = label
        self._log = log

    def execute(self) -> None:
        self._log.append(f"exec:{self._label}")

    def undo(self) -> None:
        self._log.append(f"undo:{self._label}")

    @property
    def description(self) -> str:
        return self._label


class CommandStackTests(unittest.TestCase):
    def test_push_executes_command(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        self.assertEqual(log, ["exec:a"])

    def test_undo_reverses_command(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        stack.undo()
        self.assertEqual(log, ["exec:a", "undo:a"])

    def test_redo_re_executes(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        stack.undo()
        stack.redo()
        self.assertEqual(log, ["exec:a", "undo:a", "exec:a"])

    def test_undo_at_beginning_returns_none(self) -> None:
        stack = CommandStack()
        self.assertIsNone(stack.undo())

    def test_redo_at_end_returns_none(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        self.assertIsNone(stack.redo())

    def test_push_after_undo_discards_redo_branch(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        stack.push(SimpleCommand("b", log))
        stack.undo()  # undo b
        stack.push(SimpleCommand("c", log))
        # redo should not be possible (c replaced the branch)
        self.assertFalse(stack.can_redo)
        stack.undo()  # undo c
        self.assertEqual(stack.redo_description, "c")

    def test_undo_redo_descriptions(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("paint", log))
        self.assertEqual(stack.undo_description, "paint")
        self.assertIsNone(stack.redo_description)
        stack.undo()
        self.assertIsNone(stack.undo_description)
        self.assertEqual(stack.redo_description, "paint")

    def test_can_undo_redo_flags(self) -> None:
        stack = CommandStack()
        self.assertFalse(stack.can_undo)
        self.assertFalse(stack.can_redo)
        log: list = []
        stack.push(SimpleCommand("x", log))
        self.assertTrue(stack.can_undo)
        self.assertFalse(stack.can_redo)
        stack.undo()
        self.assertFalse(stack.can_undo)
        self.assertTrue(stack.can_redo)

    def test_history_property_returns_executed_commands(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        stack.push(SimpleCommand("b", log))
        self.assertEqual(len(stack.history), 2)
        stack.undo()
        self.assertEqual(len(stack.history), 1)

    def test_clear_discards_everything(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(SimpleCommand("a", log))
        stack.clear()
        self.assertFalse(stack.can_undo)
        self.assertFalse(stack.can_redo)

    def test_max_size_trims_oldest(self) -> None:
        log: list = []
        stack = CommandStack(max_size=3)
        for i in range(5):
            stack.push(SimpleCommand(str(i), log))
        self.assertEqual(len(stack.history), 3)

    def test_zero_max_size_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CommandStack(max_size=0)

    def test_repeated_undo_at_beginning_is_safe(self) -> None:
        stack = CommandStack()
        for _ in range(5):
            self.assertIsNone(stack.undo())


class RenameCommandTests(unittest.TestCase):
    def test_rename_and_undo(self) -> None:
        entity = Entity("old_name")
        stack = CommandStack()
        stack.push(RenameEntityCommand(entity, "old_name", "new_name"))
        self.assertEqual(entity.name, "new_name")
        stack.undo()
        self.assertEqual(entity.name, "old_name")


class DeleteCommandTests(unittest.TestCase):
    def test_delete_removes_entity(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        eid = entity.entity_id
        stack = CommandStack()
        stack.push(DeleteEntityCommand(scene, entity))
        self.assertIsNone(scene.find_entity(eid))

    def test_undo_restores_entity(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        eid = entity.entity_id
        stack = CommandStack()
        stack.push(DeleteEntityCommand(scene, entity))
        stack.undo()
        self.assertIsNotNone(scene.find_entity(eid))


class ComponentCommandTests(unittest.TestCase):
    def test_component_property_add_remove_undo_and_redo(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        transform = TransformComponent()
        entity.add_component(transform)
        stack = CommandStack()

        stack.push(SetComponentPropertyCommand(scene, entity.entity_id, TransformComponent, "x", 12.0))
        self.assertEqual(transform.x, 12.0)
        stack.undo()
        self.assertEqual(transform.x, 0.0)
        stack.redo()
        self.assertEqual(transform.x, 12.0)

        stack.push(RemoveComponentCommand(scene, entity.entity_id, transform))
        self.assertNotIn(transform, entity.components)
        stack.undo()
        self.assertIn(transform, entity.components)

        other = scene.create_entity("other")
        stack.push(AddComponentCommand(scene, other.entity_id, TransformComponent))
        self.assertEqual(len(other.get_components(TransformComponent)), 1)
        stack.undo()
        self.assertEqual(len(other.get_components(TransformComponent)), 0)

    def test_component_commands_are_no_ops_for_stale_targets(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        transform = TransformComponent()
        entity.add_component(transform)
        stack = CommandStack()
        command = SetComponentPropertyCommand(scene, entity.entity_id, TransformComponent, "x", 9.0)
        scene.remove_entity(entity.entity_id)
        stack.push(command)
        self.assertEqual(transform.x, 0.0)
        self.assertFalse(stack.undo() is None)

    def test_property_command_does_not_edit_replaced_component(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        original = TransformComponent()
        entity.add_component(original)
        command = SetComponentPropertyCommand(scene, entity.entity_id, TransformComponent, "x", 9.0)
        entity.remove_component(original)
        replacement = TransformComponent()
        entity.add_component(replacement)
        CommandStack().push(command)
        self.assertEqual(replacement.x, 0.0)


if __name__ == "__main__":
    unittest.main()
