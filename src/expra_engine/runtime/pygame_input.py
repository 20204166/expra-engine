"""Pygame backend translation into backend-neutral physical input identities.

This is the single canonical owner of pygame → ``PhysicalInput`` normalization.
It knows how to translate platform/pygame event primitives into canonical
device/control strings; it carries NO gameplay meaning (it never decides that a
key or button "means" a particular action). The project's ``InputMap`` owns
which physical control triggers which logical action.

Mouse buttons use pygame's 1-based numbering, gamepad buttons/axes use pygame's
0-based numbering; the ``device`` component of ``PhysicalInput`` keeps those
namespaces distinct.
"""

from __future__ import annotations

from typing import Any

from expra_engine.runtime.input import PhysicalInput

__all__ = (
    "gamepad_axis_name",
    "gamepad_button_name",
    "keyboard_control_name",
    "mouse_button_name",
    "translate_axis_event",
)


def keyboard_control_name(pygame_module: Any, key: Any) -> str:
    """Translate a pygame key constant into a canonical keyboard control name.

    Prefers ``pygame.key.name()`` (e.g. ``K_RIGHT`` -> ``"right"``) and falls
    back to the string form of the constant when no name API is available, so
    an unknown key never produces a malformed or empty control.
    """
    key_api = getattr(pygame_module, "key", None)
    name = getattr(key_api, "name", None)
    return str(name(key)) if callable(name) else str(key)


def mouse_button_name(button: Any) -> str:
    """Translate a pygame mouse button number into a canonical mouse control name.

    Uses the engine's established ``button-<N>`` convention (1-based, matching
    pygame's ``MOUSEBUTTONDOWN``/``MOUSEBUTTONUP`` ``button`` field).
    """
    return f"button-{button}"


def gamepad_button_name(button: Any) -> str:
    """Translate a pygame joystick button index into a canonical gamepad control.

    Uses the engine's ``button-<N>`` convention on the ``gamepad`` device
    (0-based, matching pygame's ``JOYBUTTONDOWN``/``JOYBUTTONUP`` ``button``).
    """
    return f"button-{button}"


def gamepad_axis_name(axis: Any) -> str:
    """Translate a pygame joystick axis index into a canonical gamepad axis.

    Uses the engine's ``axis-<N>`` convention on the ``gamepad`` device
    (0-based, matching pygame's ``JOYAXISMOTION`` ``axis``).
    """
    return f"axis-{axis}"


def translate_event(pygame_module: Any, event: Any) -> tuple[str, PhysicalInput] | None:
    """Translate a pygame input event into ``(phase, PhysicalInput)``, else ``None``.

    Digital keyboard, mouse-button, and gamepad-button events are translated.
    Analog joystick axes use :func:`translate_axis_event` instead.
    """
    event_type = getattr(event, "type", None)
    if event_type == getattr(pygame_module, "KEYDOWN", object()):
        return "press", PhysicalInput("keyboard", keyboard_control_name(pygame_module, event.key))
    if event_type == getattr(pygame_module, "KEYUP", object()):
        return "release", PhysicalInput("keyboard", keyboard_control_name(pygame_module, event.key))
    if event_type == getattr(pygame_module, "MOUSEBUTTONDOWN", object()):
        return "press", PhysicalInput("mouse", mouse_button_name(event.button))
    if event_type == getattr(pygame_module, "MOUSEBUTTONUP", object()):
        return "release", PhysicalInput("mouse", mouse_button_name(event.button))
    if event_type == getattr(pygame_module, "JOYBUTTONDOWN", object()):
        return "press", PhysicalInput("gamepad", gamepad_button_name(event.button))
    if event_type == getattr(pygame_module, "JOYBUTTONUP", object()):
        return "release", PhysicalInput("gamepad", gamepad_button_name(event.button))
    return None


def translate_axis_event(pygame_module: Any, event: Any) -> tuple[PhysicalInput, float] | None:
    """Translate a ``JOYAXISMOTION`` event into ``(PhysicalInput, raw_value)``.

    Returns ``None`` for any event that is not an axis-motion event.
    """
    if getattr(event, "type", None) == getattr(pygame_module, "JOYAXISMOTION", object()):
        return PhysicalInput("gamepad", gamepad_axis_name(event.axis)), event.value
    return None
