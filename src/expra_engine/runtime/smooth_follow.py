"""Frame-rate-independent two-dimensional follow state."""

from __future__ import annotations

import math
from dataclasses import dataclass

from expra_engine.core.math_utils import lerp_exponential_decay


@dataclass
class SmoothFollow:
    speed: float = 5.0
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.speed) or self.speed <= 0.0:
            raise ValueError("speed must be finite and positive")

    def update(self, dt: float, target_x: float, target_y: float) -> tuple[float, float]:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if not math.isfinite(target_x) or not math.isfinite(target_y):
            raise ValueError("target coordinates must be finite")
        self.x = lerp_exponential_decay(self.x, target_x, dt, self.speed)
        self.y = lerp_exponential_decay(self.y, target_y, dt, self.speed)
        return self.x, self.y

    def snap_to(self, x: float, y: float) -> None:
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("snap coordinates must be finite")
        self.x = x
        self.y = y


__all__ = ["SmoothFollow"]
