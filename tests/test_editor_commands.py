"""Tests for the editor undo/redo command model."""

import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.core.scene.scene_instance import (
    SceneInstanceComponent,
    SceneInstanceSourceError,
)
from expra_engine.editor.commands import (
    AddComponentCommand,
    Command,
    CommandStack,
    CompositeCommand,
    CreateEntityCommand,
    CreateSceneInstanceCommand,
    DeleteEntityCommand,
    RemoveComponentCommand,
    RenameEntityCommand,
    ReparentEntityCommand,
    SetComponentPropertyCommand,
    ToggleEnabledCommand,
    TransformEntityCommand,
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

        stack.push(
            SetComponentPropertyCommand(scene, entity.entity_id, TransformComponent, "x", 12.0)
        )
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


class CreateEntityCommandTests(unittest.TestCase):
    def test_execute_is_idempotent_when_entity_already_present(self) -> None:
        """clone_entity()/create_entity() already add the entity before the
        command is pushed -- execute() must no-op rather than double-add."""
        scene = Scene("test")
        entity = scene.create_entity("hero")
        stack = CommandStack()
        stack.push(CreateEntityCommand(scene, entity))
        self.assertEqual(len(scene.entities), 1)

    def test_undo_removes_then_redo_re_adds_same_entity(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        eid = entity.entity_id
        stack = CommandStack()
        stack.push(CreateEntityCommand(scene, entity))
        stack.undo()
        self.assertIsNone(scene.find_entity(eid))
        stack.redo()
        self.assertIs(scene.find_entity(eid), entity)


class ToggleEnabledCommandTests(unittest.TestCase):
    def test_execute_and_undo_toggle_enabled_flag(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        stack = CommandStack()
        stack.push(ToggleEnabledCommand(scene, entity.entity_id, True, False))
        self.assertFalse(entity.enabled)
        stack.undo()
        self.assertTrue(entity.enabled)
        stack.redo()
        self.assertFalse(entity.enabled)

    def test_missing_entity_is_a_safe_no_op(self) -> None:
        scene = Scene("test")
        stack = CommandStack()
        stack.push(ToggleEnabledCommand(scene, "missing", True, False))  # must not raise


class TransformEntityCommandTests(unittest.TestCase):
    def test_execute_sets_full_transform_and_undo_restores_it(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")
        transform = TransformComponent(x=1.0, y=2.0, rotation=0.0, scale_x=1.0, scale_y=1.0)
        entity.add_component(transform)
        old = (1.0, 2.0, 0.0, 1.0, 1.0)
        new = (5.0, -3.0, 90.0, 2.0, 2.0)
        stack = CommandStack()
        stack.push(TransformEntityCommand(scene, entity.entity_id, old, new))
        self.assertEqual(
            (transform.x, transform.y, transform.rotation, transform.scale_x, transform.scale_y),
            new,
        )
        stack.undo()
        self.assertEqual(
            (transform.x, transform.y, transform.rotation, transform.scale_x, transform.scale_y),
            old,
        )

    def test_missing_transform_component_is_a_safe_no_op(self) -> None:
        scene = Scene("test")
        entity = scene.create_entity("hero")  # no TransformComponent attached
        stack = CommandStack()
        stack.push(
            TransformEntityCommand(
                scene, entity.entity_id, (0.0, 0.0, 0.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0, 1.0)
            )
        )  # must not raise


class CompositeCommandTests(unittest.TestCase):
    def test_execute_runs_sub_commands_in_order_undo_runs_reverse(self) -> None:
        log: list = []
        composite = CompositeCommand(
            [SimpleCommand("a", log), SimpleCommand("b", log)], "two things"
        )
        stack = CommandStack()
        stack.push(composite)
        self.assertEqual(log, ["exec:a", "exec:b"])
        stack.undo()
        self.assertEqual(log, ["exec:a", "exec:b", "undo:b", "undo:a"])

    def test_counts_as_exactly_one_undo_entry(self) -> None:
        log: list = []
        stack = CommandStack()
        stack.push(CompositeCommand([SimpleCommand("a", log), SimpleCommand("b", log)]))
        self.assertEqual(len(stack.history), 1)

    def test_description_defaults_to_change_count(self) -> None:
        log: list = []
        composite = CompositeCommand([SimpleCommand("a", log), SimpleCommand("b", log)])
        self.assertEqual(composite.description, "2 changes")

    def test_rejects_empty_command_list(self) -> None:
        with self.assertRaises(ValueError):
            CompositeCommand([])

    def test_multi_entity_delete_undo_restores_all_as_one_step(self) -> None:
        scene = Scene("test")
        hero = scene.create_entity("hero")
        villain = scene.create_entity("villain")
        stack = CommandStack()
        stack.push(
            CompositeCommand(
                [DeleteEntityCommand(scene, hero), DeleteEntityCommand(scene, villain)]
            )
        )
        self.assertEqual(len(scene.entities), 0)
        self.assertEqual(len(stack.history), 1)
        stack.undo()
        self.assertEqual({e.entity_id for e in scene.entities}, {hero.entity_id, villain.entity_id})


class ReparentEntityCommandTests(unittest.TestCase):
    def test_undo_redo_restores_and_reapplies_parent(self) -> None:
        scene = Scene("test")
        parent = scene.create_entity("parent")
        child = scene.create_entity("child")
        stack = CommandStack()
        stack.push(ReparentEntityCommand(scene, child.entity_id, None, parent.entity_id))
        self.assertEqual(child.parent_id, parent.entity_id)
        stack.undo()
        self.assertIsNone(child.parent_id)
        stack.redo()
        self.assertEqual(child.parent_id, parent.entity_id)

    def test_execute_is_a_no_op_when_already_at_target_parent(self) -> None:
        scene = Scene("test")
        parent = scene.create_entity("parent")
        child = scene.create_entity("child", parent_id=parent.entity_id)
        command = ReparentEntityCommand(scene, child.entity_id, None, parent.entity_id)
        command.execute()  # already there -- must not raise or change anything
        self.assertEqual(child.parent_id, parent.entity_id)

    def test_multi_entity_reparent_is_one_undo_step(self) -> None:
        scene = Scene("test")
        room = scene.create_entity("room")
        a = scene.create_entity("a")
        b = scene.create_entity("b")
        stack = CommandStack()
        stack.push(
            CompositeCommand(
                [
                    ReparentEntityCommand(scene, a.entity_id, None, room.entity_id),
                    ReparentEntityCommand(scene, b.entity_id, None, room.entity_id),
                ]
            )
        )
        self.assertEqual({a.parent_id, b.parent_id}, {room.entity_id})
        self.assertEqual(len(stack.history), 1)
        stack.undo()
        self.assertEqual({a.parent_id, b.parent_id}, {None})


class CreateSceneInstanceCommandTests(unittest.TestCase):
    def test_execute_materializes_source_and_undo_removes_whole_subtree(self) -> None:
        scene = Scene("level")
        room = Scene("room", scene_id="room-segment")
        room.create_entity("Wall")

        def resolve_source(_path: str) -> Scene:
            return room

        instance_root = Entity("Room Instance")
        instance_root.add_component(TransformComponent(x=5.0))
        instance_root.add_component(SceneInstanceComponent("scenes/room.json"))
        command = CreateSceneInstanceCommand(scene, instance_root, resolve_source)

        stack = CommandStack()
        stack.push(command)
        self.assertEqual({e.name for e in scene.entities}, {"Room Instance", "Wall"})

        stack.undo()
        self.assertEqual(scene.entities, ())

    def test_execute_rolls_back_root_add_when_resolution_fails(self) -> None:
        scene = Scene("level")

        def resolve_source(_path: str) -> Scene:
            raise RuntimeError("missing on disk")

        instance_root = Entity("Broken Instance")
        instance_root.add_component(SceneInstanceComponent("scenes/missing.json"))
        command = CreateSceneInstanceCommand(scene, instance_root, resolve_source)

        with self.assertRaises(SceneInstanceSourceError):
            command.execute()
        self.assertEqual(scene.entities, ())


if __name__ == "__main__":
    unittest.main()
