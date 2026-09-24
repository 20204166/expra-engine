"""Pure-data delayed tooltip state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _require_finite_non_negative(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")


@dataclass
class TooltipState:
    text: str = ""
    delay: float = 0.5
    _elapsed: float = field(default=0.0, init=False, repr=False)
    visible: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_finite_non_negative(self.delay, "delay")

    def start(self) -> None:
        self._elapsed = 0.0
        self.visible = False

    def update(self, dt: float) -> None:
        _require_finite_non_negative(dt, "dt")
        if not self.text:
            self.visible = False
            return
        self._elapsed += dt
        self.visible = self._elapsed >= self.delay

    def hide(self) -> None:
        self._elapsed = 0.0
        self.visible = False


__all__ = ["TooltipState"]
