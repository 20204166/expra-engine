"""Pure-data recent-position trail."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TrailPoint:
    x: float
    y: float
    age: float = 0.0


@dataclass
class TrailRenderer:
    max_segments: int = 20
    min_spacing: float = 0.05
    max_lifetime: float = 1.0
    _points: deque[TrailPoint] = field(default_factory=deque, init=False, repr=False)
    _last_x: float | None = field(default=None, init=False, repr=False)
    _last_y: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_segments <= 0:
            raise ValueError("max_segments must be > 0")
        if not math.isfinite(self.min_spacing) or self.min_spacing < 0.0:
            raise ValueError("min_spacing must be finite and non-negative")
        if not math.isfinite(self.max_lifetime) or self.max_lifetime <= 0.0:
            raise ValueError("max_lifetime must be finite and positive")

    @property
    def points(self) -> list[TrailPoint]:
        return list(self._points)

    def update(self, dt: float, x: float, y: float) -> None:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("trail coordinates must be finite")
        for point in self._points:
            point.age += dt
        while self._points and self._points[0].age >= self.max_lifetime:
            self._points.popleft()

        last_x, last_y = self._last_x, self._last_y
        if (
            last_x is None
            or last_y is None
            or ((x - last_x) ** 2 + (y - last_y) ** 2 >= self.min_spacing**2)
        ):
            self._points.append(TrailPoint(x, y))
            self._last_x, self._last_y = x, y

        while len(self._points) > self.max_segments:
            self._points.popleft()

    def clear(self) -> None:
        self._points.clear()
        self._last_x = None
        self._last_y = None


__all__ = ["TrailPoint", "TrailRenderer"]
