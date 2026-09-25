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


def compose_2d_pose(
    parent: tuple[float, float, float, float, float],
    child: tuple[float, float, float, float, float],
) -> tuple[float, float, float, float, float]:
    """Compose a child's local 2D pose under its parent's world pose.

    Each pose is ``(x, y, rotation_degrees, scale_x, scale_y)``. The child's
    local position is scaled and rotated by the parent, then translated by
    the parent's position; rotation sums and scale multiplies. This is the
    single canonical parent-child composition formula shared by editor pose
    queries (``Scene.world_pose``) and render-time transform extraction
    (``Transform.compose``) -- keep them delegating here rather than
    reimplementing the trigonometry twice.
    """
    px, py, parent_rotation, parent_scale_x, parent_scale_y = parent
    x, y, rotation, scale_x, scale_y = child
    angle = math.radians(parent_rotation)
    scaled_x = x * parent_scale_x
    scaled_y = y * parent_scale_y
    return (
        px + scaled_x * math.cos(angle) - scaled_y * math.sin(angle),
        py + scaled_x * math.sin(angle) + scaled_y * math.cos(angle),
        parent_rotation + rotation,
        parent_scale_x * scale_x,
        parent_scale_y * scale_y,
    )


__all__ = [
    "clamp",
    "compose_2d_pose",
    "inverselerp",
    "lerp",
    "lerp_angle",
    "lerp_exponential_decay",
    "round_to_closest",
]
