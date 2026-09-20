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


class InputMapEdgeTests(unittest.TestCase):
    def test_duplicate_binding_same_mapping_accepted(self) -> None:
        m = InputMap()
        a = ActionId("jump")
        p = PhysicalInput("keyboard", "space")
        m.bind(a, p)
        m.bind(a, p)  # exact duplicate must be silent

    def test_duplicate_binding_different_action_rejected(self) -> None:
        m = InputMap()
        p = PhysicalInput("keyboard", "space")
        m.bind(ActionId("jump"), p)
        with self.assertRaises(ValueError):
            m.bind(ActionId("crouch"), p)

    def test_rebind_while_held_releases_old_action(self) -> None:
        m = InputMap()
        a = ActionId("jump")
        p = PhysicalInput("keyboard", "space")
        m.bind(a, p)
        m.press(p)
        self.assertTrue(m.is_held(a))
        m.unbind(p)
        self.assertFalse(m.is_held(a))

    def test_press_release_ordering(self) -> None:
        m = InputMap()
        a = ActionId("fire")
        p = PhysicalInput("keyboard", "x")
        m.bind(a, p)
        pressed = m.press(p)
        released = m.release(p)
        self.assertEqual(pressed[0].phase, "pressed")
        self.assertEqual(released[0].phase, "released")

    def test_release_without_press_emits_nothing(self) -> None:
        m = InputMap()
        p = PhysicalInput("keyboard", "x")
        m.bind(ActionId("fire"), p)
        self.assertEqual(m.release(p), ())

    def test_focus_lost_releases_all_held(self) -> None:
        m = InputMap()
        p1 = PhysicalInput("keyboard", "a")
        p2 = PhysicalInput("keyboard", "b")
        m.bind(ActionId("move_left"), p1)
        m.bind(ActionId("move_right"), p2)
        m.press(p1)
        m.press(p2)
        events = m.focus_lost()
        self.assertEqual(len(events), 2)
        self.assertFalse(m.held_actions)

    def test_press_unbound_key_emits_nothing(self) -> None:
        m = InputMap()
        self.assertEqual(m.press(PhysicalInput("keyboard", "q")), ())


class GamepadAxisTests(unittest.TestCase):
    def test_inside_deadzone_is_zero(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(0.05, deadzone=0.1)
        self.assertEqual(axis.apply_deadzone(), 0.0)

    def test_at_deadzone_boundary_is_zero(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(0.1, deadzone=0.1)
        self.assertEqual(axis.apply_deadzone(), 0.0)

    def test_just_outside_deadzone_nonzero(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(0.11, deadzone=0.1)
        result = axis.apply_deadzone()
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_negative_axis(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(-0.5, deadzone=0.1)
        self.assertLess(axis.apply_deadzone(), 0.0)

    def test_full_deflection_gives_one(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(1.0, deadzone=0.2)
        self.assertAlmostEqual(axis.apply_deadzone(), 1.0)

    def test_out_of_range_value_rejected(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        with self.assertRaises(ValueError):
            GamepadAxis(1.5)

    def test_deadzone_one_rejected(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        with self.assertRaises(ValueError):
            GamepadAxis(0.5, deadzone=1.0)

    def test_zero_deadzone_never_suppresses(self) -> None:
        from expra_engine.runtime.input import GamepadAxis

        axis = GamepadAxis(0.001, deadzone=0.0)
        self.assertGreater(axis.apply_deadzone(), 0.0)
