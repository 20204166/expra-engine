"""Small numerical helpers shared by pure runtime models."""

from __future__ import annotations

import math


def clamp(value: float, floor: float, ceiling: float) -> float:
    """Return *value* constrained to the inclusive range."""
    if floor > ceiling:
        raise ValueError(f"floor ({floor}) must be <= ceiling ({ceiling})")
    return max(floor, min(ceiling, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linearly interpolate between *a* and *b* without clamping *t*."""
    return a + (b - a) * t


def inverselerp(a: float, b: float, value: float) -> float:
    """Return the interpolation parameter for *value* between *a* and *b*."""
    if a == b:
        raise ValueError("a and b must be different for inverselerp")
    return (value - a) / (b - a)


def lerp_angle(start_deg: float, end_deg: float, t: float) -> float:
    """Interpolate degrees along the shortest signed arc."""
    difference = (end_deg - start_deg + 180.0) % 360.0 - 180.0
    return start_deg + difference * t


def lerp_exponential_decay(a: float, b: float, dt: float, decay: float) -> float:
    """Move *a* toward *b* by a frame-rate-independent decay factor."""
    return b + (a - b) * math.exp(-decay * dt)


def round_to_closest(value: float, step: float) -> float:
    """Round *value* to the nearest multiple of a positive *step*."""
    if step <= 0:
        raise ValueError("step must be positive")
    return round(value / step) * step


__all__ = [
    "clamp",
    "inverselerp",
    "lerp",
    "lerp_angle",
    "lerp_exponential_decay",
    "round_to_closest",
]
