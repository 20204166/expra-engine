"""Pure-data scalar tweening."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Tween:
    start: float
    end: float
    duration: float
    easing: Callable[[float], float] = field(default=lambda t: t)
    _elapsed: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration) or self.duration <= 0.0:
            raise ValueError("duration must be finite and positive")

    @property
    def finished(self) -> bool:
        return self._elapsed >= self.duration

    @property
    def value(self) -> float:
        progress = min(self._elapsed / self.duration, 1.0)
        return self.start + (self.end - self.start) * self.easing(progress)

    def step(self, dt: float) -> float:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if not self.finished:
            self._elapsed = min(self._elapsed + dt, self.duration)
        return self.value

    def reset(self) -> None:
        self._elapsed = 0.0


__all__ = ["Tween"]
