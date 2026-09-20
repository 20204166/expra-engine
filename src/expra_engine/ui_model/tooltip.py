"""Pure-data delayed tooltip state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class TooltipState:
    text: str = ""
    delay: float = 0.5
    _elapsed: float = field(default=0.0, init=False, repr=False)
    visible: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.delay) or self.delay < 0.0:
            raise ValueError("delay must be finite and non-negative")

    def start(self) -> None:
        self._elapsed = 0.0
        self.visible = False

    def update(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if not self.text:
            self.visible = False
            return
        self._elapsed += dt
        self.visible = self._elapsed >= self.delay

    def hide(self) -> None:
        self._elapsed = 0.0
        self.visible = False


__all__ = ["TooltipState"]
