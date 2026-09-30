"""Pygame backend normalization into backend-neutral physical input identities."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.pygame_input import (
    gamepad_axis_name,
    gamepad_button_name,
    keyboard_control_name,
    mouse_button_name,
    translate_axis_event,
    translate_event,
)


def _pygame_module(key_map: dict[int, str] | None = None) -> SimpleNamespace:
    mapping = key_map or {}
    return SimpleNamespace(
        KEYDOWN=2,
        KEYUP=3,
        MOUSEBUTTONDOWN=5,
        MOUSEBUTTONUP=6,
        JOYBUTTONDOWN=7,
        JOYBUTTONUP=8,
        JOYAXISMOTION=9,
        key=SimpleNamespace(name=lambda key: mapping.get(key, "unknown key")),
    )


class KeyboardControlNameTests(unittest.TestCase):
    def test_uses_key_name_api(self) -> None:
        pygame_module = _pygame_module({11: "right"})
        self.assertEqual(keyboard_control_name(pygame_module, 11), "right")

    def test_unknown_key_falls_back_to_a_safe_string(self) -> None:
        pygame_module = _pygame_module({})
        name = keyboard_control_name(pygame_module, 9999)
        self.assertEqual(name, "unknown key")
        self.assertNotEqual(name, "")

    def test_no_key_api_falls_back_to_string(self) -> None:
        pygame_module = SimpleNamespace()
        self.assertEqual(keyboard_control_name(pygame_module, 42), "42")


class MouseControlNameTests(unittest.TestCase):
    def test_mouse_buttons_are_one_based(self) -> None:
        self.assertEqual(mouse_button_name(1), "button-1")
        self.assertEqual(mouse_button_name(4), "button-4")


class GamepadNameTests(unittest.TestCase):
    def test_gamepad_buttons_and_axes_are_zero_based(self) -> None:
        self.assertEqual(gamepad_button_name(0), "button-0")
        self.assertEqual(gamepad_axis_name(1), "axis-1")


class TranslateEventTests(unittest.TestCase):
    def test_keydown_and_keyup(self) -> None:
        pygame_module = _pygame_module({11: "right"})
        down = translate_event(pygame_module, SimpleNamespace(type=2, key=11))
        up = translate_event(pygame_module, SimpleNamespace(type=3, key=11))
        self.assertEqual(down, ("press", PhysicalInput("keyboard", "right")))
        self.assertEqual(up, ("release", PhysicalInput("keyboard", "right")))

    def test_mouse_down_and_up(self) -> None:
        pygame_module = _pygame_module()
        down = translate_event(pygame_module, SimpleNamespace(type=5, button=1))
        up = translate_event(pygame_module, SimpleNamespace(type=6, button=3))
        self.assertEqual(down, ("press", PhysicalInput("mouse", "button-1")))
        self.assertEqual(up, ("release", PhysicalInput("mouse", "button-3")))

    def test_gamepad_button_down_and_up(self) -> None:
        pygame_module = _pygame_module()
        down = translate_event(pygame_module, SimpleNamespace(type=7, button=0))
        up = translate_event(pygame_module, SimpleNamespace(type=8, button=3))
        self.assertEqual(down, ("press", PhysicalInput("gamepad", "button-0")))
        self.assertEqual(up, ("release", PhysicalInput("gamepad", "button-3")))

    def test_gamepad_axis_motion(self) -> None:
        pygame_module = _pygame_module()
        translated = translate_axis_event(
            pygame_module, SimpleNamespace(type=9, axis=1, value=-0.5)
        )
        self.assertEqual(translated, (PhysicalInput("gamepad", "axis-1"), -0.5))

    def test_axis_translate_ignores_non_axis_events(self) -> None:
        pygame_module = _pygame_module()
        self.assertIsNone(translate_axis_event(pygame_module, SimpleNamespace(type=7, button=0)))

    def test_unrelated_event_returns_none(self) -> None:
        pygame_module = _pygame_module()
        self.assertIsNone(translate_event(pygame_module, SimpleNamespace(type=99)))


if __name__ == "__main__":
    unittest.main()
