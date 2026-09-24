"""Typed, renderer-neutral state for common UI controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Literal, TypeVar

__all__ = (
    "Button",
    "ButtonVisualState",
    "Progress",
    "ProgressSegment",
    "SelectionGroup",
    "Slider",
    "StateChange",
    "Toggle",
)

T = TypeVar("T")
SelectionMode = Literal["multi", "radio"]


@dataclass(frozen=True)
class StateChange[T]:
    """A state transition returned to an adapter or caller."""

    old: T
    new: T

    @property
    def changed(self) -> bool:
        return self.old != self.new


class ButtonVisualState(Enum):
    NORMAL = "normal"
    HOVER = "hover"
    PRESSED = "pressed"
    DISABLED = "disabled"
    SELECTED = "selected"


@dataclass
class Button:
    """Button interaction flags and their renderer-neutral visual state."""

    enabled: bool = True
    hovered: bool = False
    pressed: bool = False
    selected: bool = False

    @property
    def visual_state(self) -> ButtonVisualState:
        if not self.enabled:
            return ButtonVisualState.DISABLED
        if self.pressed:
            return ButtonVisualState.PRESSED
        if self.hovered:
            return ButtonVisualState.HOVER
        if self.selected:
            return ButtonVisualState.SELECTED
        return ButtonVisualState.NORMAL

    def update(
        self,
        *,
        enabled: bool | None = None,
        hovered: bool | None = None,
        pressed: bool | None = None,
        selected: bool | None = None,
    ) -> StateChange[ButtonVisualState]:
        old = self.visual_state
        if enabled is not None:
            self.enabled = enabled
        if hovered is not None:
            self.hovered = hovered
        if pressed is not None:
            self.pressed = pressed
        if selected is not None:
            self.selected = selected
        return StateChange(old, self.visual_state)


@dataclass
class Toggle:
    """A binary value with explicit enabled-state transitions."""

    value: bool = False
    enabled: bool = True

    def toggle(self) -> StateChange[bool]:
        old = self.value
        if self.enabled:
            self.value = not self.value
        return StateChange(old, self.value)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


@dataclass
class Slider:
    """A stepped numeric value with separate live and committed updates."""

    minimum: float
    maximum: float
    default: float | None = None
    step: float = 1.0

    def __post_init__(self) -> None:
        self.minimum = _finite(self.minimum, "minimum")
        self.maximum = _finite(self.maximum, "maximum")
        self.step = _finite(self.step, "step")
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if self.step <= 0.0:
            raise ValueError("step must be positive")
        initial = self.maximum if self.default is None else _finite(self.default, "default")
        if not self.minimum <= initial <= self.maximum:
            raise ValueError("default must be within the slider range")
        self.value = self._snap(initial)
        self.committed_value = self.value

    def _snap(self, value: float) -> float:
        bounded = _clamp(_finite(value, "value"), self.minimum, self.maximum)
        steps = round((bounded - self.minimum) / self.step)
        return _clamp(self.minimum + steps * self.step, self.minimum, self.maximum)

    def live_change(self, value: float) -> StateChange[float]:
        old = self.value
        self.value = self._snap(value)
        return StateChange(old, self.value)

    def commit(self, value: float) -> StateChange[float]:
        change = self.live_change(value)
        self.committed_value = self.value
        return change


@dataclass
class SelectionGroup:
    """A validated radio or multi-selection set."""

    members: tuple[str, ...]
    minimum: int = 0
    maximum: int | None = None
    mode: SelectionMode = "multi"
    selected: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.members = tuple(self.members)
        self.selected = tuple(self.selected)
        self.disabled = tuple(self.disabled)
        if len(set(self.members)) != len(self.members):
            raise ValueError("members must not contain duplicates")
        if self.mode not in ("multi", "radio"):
            raise ValueError("mode must be 'multi' or 'radio'")
        maximum = 1 if self.mode == "radio" and self.maximum is None else self.maximum
        if maximum is None:
            maximum = len(self.members)
        self.maximum = maximum
        if self.minimum < 0 or maximum < self.minimum or maximum > len(self.members):
            raise ValueError("selection constraints are invalid")
        if self.mode == "radio" and maximum > 1:
            raise ValueError("radio groups can select at most one member")
        if len(set(self.selected)) != len(self.selected) or not set(self.selected) <= set(
            self.members
        ):
            raise ValueError("selected members must be unique members")
        if len(self.selected) < self.minimum or len(self.selected) > maximum:
            raise ValueError("initial selection violates selection constraints")
        if not set(self.disabled) <= set(self.members):
            raise ValueError("disabled members must be members of the group")

    def select(self, member: str, *, selected: bool = True) -> StateChange[tuple[str, ...]]:
        if member not in self.members:
            raise ValueError("unknown selection member")
        old = self.selected
        if member in self.disabled:
            return StateChange(old, old)
        current = list(self.selected)
        maximum = self.maximum if self.maximum is not None else len(self.members)
        if selected and member not in current:
            if self.mode == "radio":
                current = [member]
            elif len(current) >= maximum:
                raise ValueError("maximum selection reached")
            else:
                current.append(member)
        elif not selected and member in current:
            if len(current) <= self.minimum:
                raise ValueError("minimum selection required")
            current.remove(member)
        self.selected = tuple(current)
        return StateChange(old, self.selected)


@dataclass(frozen=True)
class ProgressSegment:
    """Metadata describing one logical range within a progress control."""

    label: str
    start: float
    end: float


@dataclass
class Progress:
    """Generic bounded progress data; domain meanings stay with callers."""

    minimum: float
    maximum: float
    value: float = 0.0
    text: str | None = None
    segments: tuple[ProgressSegment, ...] = ()

    def __post_init__(self) -> None:
        self.minimum = _finite(self.minimum, "minimum")
        self.maximum = _finite(self.maximum, "maximum")
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        self.value = _clamp(_finite(self.value, "value"), self.minimum, self.maximum)
        self.segments = tuple(self.segments)
        for segment in self.segments:
            start = _finite(segment.start, "segment start")
            end = _finite(segment.end, "segment end")
            if start < self.minimum or end > self.maximum or start > end:
                raise ValueError("progress segment is outside the progress range")
