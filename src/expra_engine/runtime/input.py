"""Backend-neutral physical input bindings and semantic action state."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = (
    "ActionEvent",
    "ActionId",
    "Binding",
    "InputMap",
    "PhysicalInput",
)


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
        if not self.device or not self.control:
            raise ValueError("physical input device and control cannot be empty")
        object.__setattr__(self, "device", self.device.lower())
        object.__setattr__(self, "control", self.control.lower())
        object.__setattr__(
            self,
            "modifiers",
            frozenset(modifier.lower() for modifier in self.modifiers),
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

    def is_held(self, action: ActionId) -> bool:
        """Return whether any binding for *action* is held."""
        return action in self.held_actions

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
        return tuple(
            ActionEvent(binding.action, "released", binding.physical) for binding in held
        )
