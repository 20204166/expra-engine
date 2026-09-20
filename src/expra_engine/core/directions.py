"""Named unit-vector direction constants for movement and facing."""

from __future__ import annotations

import math

Direction = tuple[float, float]

UP: Direction = (0.0, 1.0)
DOWN: Direction = (0.0, -1.0)
LEFT: Direction = (-1.0, 0.0)
RIGHT: Direction = (1.0, 0.0)

_DIAGONAL = math.sqrt(2.0) / 2.0
UP_LEFT: Direction = (-_DIAGONAL, _DIAGONAL)
UP_RIGHT: Direction = (_DIAGONAL, _DIAGONAL)
DOWN_LEFT: Direction = (-_DIAGONAL, -_DIAGONAL)
DOWN_RIGHT: Direction = (_DIAGONAL, -_DIAGONAL)

ALL: tuple[Direction, ...] = (
    UP,
    DOWN,
    LEFT,
    RIGHT,
    UP_LEFT,
    UP_RIGHT,
    DOWN_LEFT,
    DOWN_RIGHT,
)

__all__ = [
    "ALL",
    "DOWN",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "LEFT",
    "RIGHT",
    "UP",
    "UP_LEFT",
    "UP_RIGHT",
]
