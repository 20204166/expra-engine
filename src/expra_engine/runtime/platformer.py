"""Pure-data 2D platformer movement state with coyote time."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class PlatformerPhase(Enum):
    GROUNDED = "grounded"
    AIRBORNE = "airborne"
    COYOTE = "coyote"


@dataclass
class PlatformerController2d:
    max_jumps: int = 2
    jump_impulse: float = 8.0
    gravity: float = 20.0
    move_speed: float = 5.0
    coyote_time: float = 0.1
    min_x: float = float("-inf")
    max_x: float = float("inf")
    _vx: float = field(default=0.0, init=False)
    _vy: float = field(default=0.0, init=False)
    _x: float = field(default=0.0, init=False)
    _y: float = field(default=0.0, init=False)
    _jumps_left: int = field(default=0, init=False)
    _phase: PlatformerPhase = field(default=PlatformerPhase.AIRBORNE, init=False)
    _coyote_remaining: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.max_jumps < 1:
            raise ValueError("max_jumps must be >= 1")
        if (
            not all(
                math.isfinite(value)
                for value in (self.jump_impulse, self.gravity, self.move_speed, self.coyote_time)
            )
            or self.jump_impulse <= 0.0
            or self.gravity <= 0.0
            or self.move_speed < 0.0
            or self.coyote_time < 0.0
        ):
            raise ValueError("movement values are invalid")
        if self.min_x > self.max_x:
            raise ValueError("min_x must be <= max_x")
        self._jumps_left = self.max_jumps

    @property
    def position(self) -> tuple[float, float]:
        return self._x, self._y

    @property
    def velocity(self) -> tuple[float, float]:
        return self._vx, self._vy

    @property
    def grounded(self) -> bool:
        return self._phase == PlatformerPhase.GROUNDED

    @property
    def phase(self) -> PlatformerPhase:
        return self._phase

    @property
    def jumps_left(self) -> int:
        return self._jumps_left

    def land(self) -> None:
        self._phase = PlatformerPhase.GROUNDED
        self._jumps_left = self.max_jumps
        self._vy = 0.0
        self._coyote_remaining = 0.0

    def leave_ground(self) -> None:
        if self._phase == PlatformerPhase.GROUNDED:
            self._phase = PlatformerPhase.COYOTE
            self._coyote_remaining = self.coyote_time
            self._jumps_left = max(0, self._jumps_left - 1)

    def jump(self) -> bool:
        if self._phase in (PlatformerPhase.GROUNDED, PlatformerPhase.COYOTE):
            self._jumps_left = max(0, self._jumps_left - 1)
        elif self._jumps_left > 0:
            self._jumps_left -= 1
        else:
            return False
        self._vy = self.jump_impulse
        self._phase = PlatformerPhase.AIRBORNE
        self._coyote_remaining = 0.0
        return True

    def update(self, dt: float, move_x: float) -> None:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if not math.isfinite(move_x):
            raise ValueError("move_x must be finite")
        if self._phase == PlatformerPhase.COYOTE:
            self._coyote_remaining -= dt
            if self._coyote_remaining <= 0.0:
                self._phase = PlatformerPhase.AIRBORNE
        self._vx = move_x * self.move_speed
        if self._phase != PlatformerPhase.GROUNDED:
            self._vy -= self.gravity * dt
        self._x = max(self.min_x, min(self.max_x, self._x + self._vx * dt))
        self._y += self._vy * dt


__all__ = ["PlatformerController2d", "PlatformerPhase"]
