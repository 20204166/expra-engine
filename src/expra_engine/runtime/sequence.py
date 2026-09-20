"""Caller-driven callable-chain scheduling with no threads or Tk."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Func:
    fn: Callable[..., Any]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __call__(self) -> None:
        self.fn(*self.args, **self.kwargs)


@dataclass
class Wait:
    duration: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration) or self.duration < 0.0:
            raise ValueError("Wait duration must be finite and non-negative")


class Sequence:
    def __init__(self, *steps: Func | Wait, loop: bool = False) -> None:
        self._steps = list(steps)
        self._loop = loop
        self._index = 0
        self._wait_remaining = 0.0
        self.finished = False

    def update(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if self.finished:
            return
        if not self._steps:
            self.finished = True
            return

        remaining = dt
        while self._index < len(self._steps):
            step = self._steps[self._index]
            if isinstance(step, Func):
                step()
                self._index += 1
                continue

            wait_remaining = step.duration - self._wait_remaining
            if remaining < wait_remaining:
                self._wait_remaining += remaining
                return
            remaining -= wait_remaining
            self._wait_remaining = 0.0
            self._index += 1

        if self._loop:
            self._index = 0
            return
        self.finished = True

    def reset(self) -> None:
        self._index = 0
        self._wait_remaining = 0.0
        self.finished = False


__all__ = ["Func", "Sequence", "Wait"]
