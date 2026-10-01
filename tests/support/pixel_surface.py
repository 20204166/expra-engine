"""Small assertions over real Pygame surface pixels."""

from __future__ import annotations

from typing import Any


def color_bounds(surface: Any, rgb: tuple[int, int, int]) -> tuple[int, int, int, int]:
    """Return the inclusive pixel bounds for one RGB color or fail if absent."""
    width, height = surface.get_size()
    points = [
        (x, y)
        for x in range(width)
        for y in range(height)
        if surface.get_at((x, y))[:3] == rgb
    ]
    assert points, f"no surface pixels matched {rgb!r}"
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )
