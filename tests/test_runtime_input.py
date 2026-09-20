"""Tests for backend-neutral, instance-scoped action maps."""

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.runtime.input import (
    ActionEvent,
    ActionId,
    InputMap,
    PhysicalInput,
)


class TestRuntimeInput(unittest.TestCase):
    def test_resolves_physical_input_to_semantic_action_events(self) -> None:
        jump = ActionId("jump")
        space = PhysicalInput("keyboard", "space")
        input_map = InputMap()
        input_map.bind(jump, space)

        events = input_map.press(space)

        self.assertEqual(events, (ActionEvent(jump, "pressed", space),))
        self.assertEqual(input_map.held_actions, frozenset({jump}))

    def test_release_clears_held_state_and_emits_release(self) -> None:
        jump = ActionId("jump")
        space = PhysicalInput("keyboard", "space")
        input_map = InputMap()
        input_map.bind(jump, space)
        input_map.press(space)

        events = input_map.release(space)

        self.assertEqual(events, (ActionEvent(jump, "released", space),))
        self.assertEqual(input_map.held_actions, frozenset())
        self.assertFalse(input_map.is_held(jump))

    def test_modifier_combinations_are_distinct_bindings(self) -> None:
        plain = PhysicalInput("keyboard", "s")
        modified = PhysicalInput("keyboard", "s", frozenset({"ctrl", "shift"}))
        save = ActionId("save")
        input_map = InputMap()
        input_map.bind(save, modified)

        self.assertEqual(input_map.press(plain), ())
        self.assertEqual(input_map.press(modified), (ActionEvent(save, "pressed", modified),))

    def test_binding_identifiers_are_immutable_and_rebinding_rejects_collisions(self) -> None:
        jump = ActionId("jump")
        fire = ActionId("fire")
        key = PhysicalInput("keyboard", "x")
        input_map = InputMap()
        input_map.bind(jump, key)

        with self.assertRaises(ValueError):
            input_map.bind(fire, key)
        with self.assertRaises(FrozenInstanceError):
            jump.value = "other"  # type: ignore[misc]

    def test_unbind_absent_binding_is_a_noop(self) -> None:
        input_map = InputMap()

        self.assertFalse(input_map.unbind(PhysicalInput("mouse", "button-1")))

    def test_focus_loss_releases_all_held_actions_and_resets_state(self) -> None:
        jump = ActionId("jump")
        fire = ActionId("fire")
        jump_key = PhysicalInput("keyboard", "space")
        fire_button = PhysicalInput("mouse", "button-1")
        input_map = InputMap()
        input_map.bind(jump, jump_key)
        input_map.bind(fire, fire_button)
        input_map.press(jump_key)
        input_map.press(fire_button)

        events = input_map.focus_lost()

        self.assertEqual(
            events,
            (
                ActionEvent(fire, "released", fire_button),
                ActionEvent(jump, "released", jump_key),
            ),
        )
        self.assertEqual(input_map.held_actions, frozenset())

    def test_identifiers_are_neutral_across_input_devices(self) -> None:
        action_ids = (
            (ActionId("keyboard-action"), PhysicalInput("keyboard", "key-a")),
            (ActionId("mouse-action"), PhysicalInput("mouse", "button-primary")),
            (ActionId("controller-action"), PhysicalInput("controller", "button-a")),
            (ActionId("touch-action"), PhysicalInput("touch", "contact-primary")),
        )
        input_map = InputMap()
        for action, physical in action_ids:
            input_map.bind(action, physical)

        for action, physical in action_ids:
            self.assertEqual(input_map.press(physical), (ActionEvent(action, "pressed", physical),))

    def test_input_instances_do_not_share_bindings_or_held_state(self) -> None:
        jump = ActionId("jump")
        space = PhysicalInput("keyboard", "space")
        first = InputMap()
        second = InputMap()
        first.bind(jump, space)

        first.press(space)

        self.assertTrue(first.is_held(jump))
        self.assertFalse(second.is_held(jump))
        self.assertEqual(second.press(space), ())


if __name__ == "__main__":
    unittest.main()
