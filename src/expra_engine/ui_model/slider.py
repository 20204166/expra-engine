"""Renderer-neutral slider state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SliderModel:
    min_value: float = 0.0
    max_value: float = 1.0
    step: float = 0.0
    _value: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.min_value, self.max_value)):
            raise ValueError("slider bounds must be finite")
        if self.min_value >= self.max_value:
            raise ValueError("min_value must be < max_value")
        if not math.isfinite(self.step) or self.step < 0.0:
            raise ValueError("step must be finite and non-negative")
        self._value = self.min_value

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        clamped = max(self.min_value, min(self.max_value, value))
        if self.step > 0.0:
            steps = round((clamped - self.min_value) / self.step)
            clamped = self.min_value + steps * self.step
            clamped = max(self.min_value, min(self.max_value, clamped))
        self._value = clamped

    @property
    def fraction(self) -> float:
        return (self._value - self.min_value) / (self.max_value - self.min_value)


__all__ = ["SliderModel"]
