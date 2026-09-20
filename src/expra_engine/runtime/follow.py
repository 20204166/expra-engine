"""Renderer-neutral 2D follow math."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite

from expra_engine.core import math_utils

__all__ = ("exponential_follow",)

Vec2 = Sequence[float]


def exponential_follow(
    current: Vec2,
    target: Vec2,
    delta: float,
    speed: float,
    offset: Vec2 = (0.0, 0.0),
) -> Vec2:
    """Move ``current`` toward ``target + offset`` by exponential decay."""
    if not isfinite(delta) or delta < 0.0:
        raise ValueError("delta must be finite and non-negative")
    if not isfinite(speed) or speed < 0.0:
        raise ValueError("speed must be finite and non-negative")

    destination = (float(target[0]) + float(offset[0]), float(target[1]) + float(offset[1]))
    return (
        math_utils.lerp_exponential_decay(float(current[0]), destination[0], delta, speed),
        math_utils.lerp_exponential_decay(float(current[1]), destination[1], delta, speed),
    )
