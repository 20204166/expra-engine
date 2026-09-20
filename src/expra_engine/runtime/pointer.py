"""Backend-neutral pointer events and instance-local interaction tracking."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

__all__ = ("PointerEvent", "PointerTracker")


@dataclass(frozen=True, slots=True)
class PointerEvent:
    """An immutable semantic pointer event produced by a tracker."""

    kind: str
    position: tuple[float, float]
    timestamp: float
    target: str | None = None
    button: str = "primary"


class PointerTracker:
    """Track one pointer's interaction state without backend or global state."""

    def __init__(self, *, double_click_interval: float = 0.3) -> None:
        if not isfinite(double_click_interval) or double_click_interval < 0.0:
            raise ValueError("double_click_interval must be finite and nonnegative")
        self.double_click_interval = double_click_interval
        self.hovered: str | None = None
        self.captured: str | None = None
        self.held: frozenset[str] = frozenset()
        self.dragging = False
        self._last_position = (0.0, 0.0)
        self._last_click_target: str | None = None
        self._last_click_time: float | None = None

    @staticmethod
    def _position(position: tuple[float, float]) -> tuple[float, float]:
        if len(position) != 2 or not all(isfinite(float(value)) for value in position):
            raise ValueError("pointer position must contain two finite values")
        return (float(position[0]), float(position[1]))

    @staticmethod
    def _event(
        kind: str,
        position: tuple[float, float],
        timestamp: float,
        target: str | None,
        button: str = "primary",
    ) -> PointerEvent:
        return PointerEvent(kind, position, float(timestamp), target, button)

    def move(
        self,
        position: tuple[float, float],
        *,
        target: str | None,
        timestamp: float,
    ) -> tuple[PointerEvent, ...]:
        position = self._position(position)
        events: list[PointerEvent] = []
        if target != self.hovered:
            if self.hovered is not None:
                events.append(self._event("leave", position, timestamp, self.hovered))
            if target is not None:
                events.append(self._event("enter", position, timestamp, target))
            self.hovered = target
        if self.held and position != self._last_position:
            drag_target = self.captured
            if not self.dragging:
                self.dragging = True
                events.append(self._event("drag_start", position, timestamp, drag_target))
            events.append(self._event("drag", position, timestamp, drag_target))
        self._last_position = position
        return tuple(events)

    def press(
        self,
        *,
        button: str = "primary",
        timestamp: float,
    ) -> tuple[PointerEvent, ...]:
        target = self.hovered
        self.captured = target
        self.held = self.held | {button}
        return (self._event("press", self._last_position, timestamp, target, button),)

    def release(
        self,
        position: tuple[float, float],
        *,
        target: str | None,
        button: str = "primary",
        timestamp: float,
    ) -> tuple[PointerEvent, ...]:
        position = self._position(position)
        owner = self.captured
        events = [self._event("release", position, timestamp, owner, button)]
        if not self.dragging:
            if (
                self._last_click_target == owner
                and self._last_click_time is not None
                and float(timestamp) - self._last_click_time <= self.double_click_interval
            ):
                events.append(self._event("double_click", position, timestamp, owner, button))
                self._last_click_target = None
                self._last_click_time = None
            else:
                events.append(self._event("click", position, timestamp, owner, button))
                self._last_click_target = owner
                self._last_click_time = float(timestamp)
        else:
            events.append(self._event("drop", position, timestamp, owner, button))
        self.held = self.held - {button}
        self.captured = None
        self.dragging = False
        self._last_position = position
        return tuple(events)

    def focus_lost(self, *, timestamp: float) -> tuple[PointerEvent, ...]:
        self.held = frozenset()
        self.captured = None
        self.dragging = False
        self._last_click_target = None
        self._last_click_time = None
        return (self._event("focus_lost", self._last_position, timestamp, None),)
