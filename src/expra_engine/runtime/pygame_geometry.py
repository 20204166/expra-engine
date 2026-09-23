"""Pixel-space geometry helpers for the Pygame renderer."""

from __future__ import annotations

import math

from expra_engine.runtime.rendering import RenderContext, RenderItem, Transform

__all__ = ("projected_rectangle_points",)


def projected_rectangle_points(
    item: RenderItem,
    transform: Transform,
    context: RenderContext,
) -> tuple[tuple[int, int], ...]:
    """Project a transformed rectangle into integer Pygame points."""
    half_width = abs(item.primitive.size[0] * transform.scale[0]) / 2.0
    half_height = abs(item.primitive.size[1] * transform.scale[1]) / 2.0
    angle = math.radians(transform.rotation)
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    points: list[tuple[int, int]] = []
    for local_x, local_y in (
        (-half_width, -half_height),
        (-half_width, half_height),
        (half_width, half_height),
        (half_width, -half_height),
    ):
        world_point = (
            transform.position[0] + local_x * cos_angle - local_y * sin_angle,
            transform.position[1] + local_x * sin_angle + local_y * cos_angle,
        )
        projected = context.camera.project(world_point, context.viewport)
        points.append((round(projected[0]), round(projected[1])))
    return tuple(points)
