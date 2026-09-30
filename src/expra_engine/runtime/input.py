"""Backend-neutral physical input bindings and semantic action state."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = (
    "ActionEvent",
    "ActionId",
    "Binding",
    "GamepadAxis",
    "InputMap",
    "PhysicalInput",
)

from math import isfinite as _isfinite


@dataclass(frozen=True, slots=True)
class ActionId:
    """An immutable gameplay-facing action identifier."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("action identifier cannot be empty")


@dataclass(frozen=True, slots=True)
class PhysicalInput:
    """A backend-neutral physical control and its exact modifiers."""

    device: str
    control: str
    modifiers: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        device = self.device.strip().lower()
        control = self.control.strip().lower()
        if not device or not control:
            raise ValueError("physical input device and control cannot be empty")
        object.__setattr__(self, "device", device)
        object.__setattr__(self, "control", control)
        object.__setattr__(
            self,
            "modifiers",
            frozenset(
                modifier
                for modifier in (item.strip().lower() for item in self.modifiers)
                if modifier
            ),
        )


@dataclass(frozen=True, slots=True)
class Binding:
    """An immutable mapping between one physical input and one action."""

    action: ActionId
    physical: PhysicalInput


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """A semantic action transition emitted by an :class:`InputMap`."""

    action: ActionId
    phase: str
    physical: PhysicalInput


class InputMap:
    """An instance-scoped physical-input to semantic-action map."""

    def __init__(self) -> None:
        self._bindings: dict[PhysicalInput, Binding] = {}
        self._held: set[Binding] = set()
        self._axis_bindings: dict[PhysicalInput, tuple[ActionId, float]] = {}
        self._axes: dict[str, float] = {}

    def bind(self, action: ActionId, physical: PhysicalInput) -> Binding:
        """Add a binding, rejecting a physical-control collision."""
        binding = Binding(action, physical)
        existing = self._bindings.get(physical)
        if existing is not None and existing != binding:
            raise ValueError(f"physical input already bound: {physical!r}")
        self._bindings[physical] = binding
        return binding

    def unbind(self, physical: PhysicalInput) -> bool:
        """Remove a binding, returning ``False`` when it was absent."""
        binding = self._bindings.pop(physical, None)
        if binding is None:
            return False
        self._held.discard(binding)
        return True

    def clear(self) -> None:
        """Remove all project bindings and transient input state."""
        self._bindings.clear()
        self._held.clear()
        self._axis_bindings.clear()
        self._axes.clear()

    def press(self, physical: PhysicalInput) -> tuple[ActionEvent, ...]:
        """Resolve a physical press into one semantic action event."""
        binding = self._bindings.get(physical)
        if binding is None or binding in self._held:
            return ()
        self._held.add(binding)
        return (ActionEvent(binding.action, "pressed", physical),)

    def release(self, physical: PhysicalInput) -> tuple[ActionEvent, ...]:
        """Resolve a physical release and clear its held state."""
        binding = self._bindings.get(physical)
        if binding is None or binding not in self._held:
            return ()
        self._held.remove(binding)
        return (ActionEvent(binding.action, "released", physical),)

    @property
    def held_actions(self) -> frozenset[ActionId]:
        """Return the currently held semantic actions."""
        return frozenset(binding.action for binding in self._held)

    def is_held(self, action: ActionId | str) -> bool:
        """Return whether any binding for *action* is held."""
        value = action.value if isinstance(action, ActionId) else action
        return any(item.value == value for item in self.held_actions)

    def bind_axis(
        self, action: ActionId | str, physical: PhysicalInput, *, deadzone: float = 0.1
    ) -> tuple[ActionId, float]:
        """Bind a physical analog axis to an action with a deadzone.

        ``deadzone`` must be finite and in ``[0, 1)``. Rebinding the same
        physical axis to a different action (or a different deadzone) is
        rejected; an exact duplicate is a no-op.
        """
        action_id = action if isinstance(action, ActionId) else ActionId(action)
        deadzone_value = float(deadzone)
        if not _isfinite(deadzone_value) or not 0.0 <= deadzone_value < 1.0:
            raise ValueError("deadzone must be finite and in [0, 1)")
        binding = (action_id, deadzone_value)
        existing = self._axis_bindings.get(physical)
        if existing is not None and existing != binding:
            raise ValueError(f"physical axis already bound: {physical!r}")
        self._axis_bindings[physical] = binding
        return binding

    def unbind_axis(self, physical: PhysicalInput) -> bool:
        """Remove an axis binding, returning ``False`` when it was absent."""
        return self._axis_bindings.pop(physical, None) is not None

    def set_axis(self, physical: PhysicalInput, value: float) -> None:
        """Update an action's analog value from a bound physical axis.

        Non-numeric or non-finite values are safely ignored, and out-of-range
        values are clamped to ``[-1, 1]`` so a driver reporting a value slightly
        outside that range cannot crash gameplay. The deadzone is applied
        through :class:`GamepadAxis`.
        """
        bound = self._axis_bindings.get(physical)
        if bound is None:
            return
        action_id, deadzone = bound
        try:
            raw = float(value)
        except (TypeError, ValueError):
            return
        if not _isfinite(raw):
            return
        raw = max(-1.0, min(1.0, raw))
        self._axes[action_id.value] = GamepadAxis(raw, deadzone).apply_deadzone()

    def axis_value(self, action: ActionId | str) -> float:
        """Return the current analog value for *action* (0.0 when none)."""
        value = action.value if isinstance(action, ActionId) else action
        return self._axes.get(value, 0.0)

    def reset_held(self) -> None:
        """Clear all transient input state without emitting release events.

        Used at runtime teardown (e.g. ``Engine.stop()``) so a control held
        across a play/stop boundary cannot leak a stale "held" action or axis
        value into the next play session.
        """
        self._held.clear()
        self._axes.clear()

    def focus_lost(self) -> tuple[ActionEvent, ...]:
        """Release every held binding in deterministic order."""
        held = sorted(
            self._held,
            key=lambda binding: (
                binding.action.value,
                binding.physical.device,
                binding.physical.control,
                tuple(sorted(binding.physical.modifiers)),
            ),
        )
        self._held.clear()
        self._axes.clear()
        return tuple(ActionEvent(binding.action, "released", binding.physical) for binding in held)


@dataclass(frozen=True, slots=True)
class GamepadAxis:
    """A single gamepad stick axis with configurable deadzone.

    ``value`` is the raw hardware value in [-1, 1].
    ``apply_deadzone()`` returns 0.0 when the value is inside the deadzone
    and rescales the remainder to the full [-1, 1] range (linear rescale
    deadzone, not simple zero-out).

    ``deadzone`` must be in [0, 1).  A deadzone of 0.0 never suppresses.

    Consumed by ``PygameRuntime`` via ``InputMap.set_axis()``, which clamps the
    raw ``JOYAXISMOTION`` value to ``[-1, 1]`` before applying the deadzone.
    """

    value: float
    deadzone: float = 0.1

    def __post_init__(self) -> None:
        v = float(self.value)
        d = float(self.deadzone)
        if not _isfinite(v) or not -1.0 <= v <= 1.0:
            raise ValueError(f"axis value must be in [-1, 1], got {v!r}")
        if not _isfinite(d) or not 0.0 <= d < 1.0:
            raise ValueError(f"deadzone must be in [0, 1), got {d!r}")
        object.__setattr__(self, "value", v)
        object.__setattr__(self, "deadzone", d)

    def apply_deadzone(self) -> float:
        """Return value after deadzone application, rescaled to [-1, 1]."""
        magnitude = abs(self.value)
        if magnitude <= self.deadzone:
            return 0.0
        sign = 1.0 if self.value >= 0.0 else -1.0
        return sign * (magnitude - self.deadzone) / (1.0 - self.deadzone)
