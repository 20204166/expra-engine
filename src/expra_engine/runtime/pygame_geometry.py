"""Pixel-space geometry helpers for the Pygame renderer."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, cast

from expra_engine.runtime.canvas_effects import modulate_color
from expra_engine.runtime.rendering import Color, RenderContext, RenderItem, Transform

__all__ = ("draw_rounded_rectangle", "projected_rectangle_points")


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


def draw_rounded_rectangle(
    renderer: Any,
    surface: Any,
    draw: Any,
    item: RenderItem,
    transform: Transform,
    context: RenderContext,
    position: tuple[int, int],
    color: tuple[int, ...],
    modulation: Color,
) -> None:
    """Draw a rounded_rectangle primitive, rotated or not, with an optional outline.

    ``radius`` on a rounded_rectangle is a corner radius, not a circumscribed
    extent like it is for circle/point -- scaled the same way circle's radius
    is (by the larger axis scale, against camera/viewport width) for
    consistency with the existing primitive conventions. ``renderer`` supplies
    the pygame module and the renderer's own rect/color helpers (kept on
    PygameRenderer so fake-pygame test doubles without a real ``pygame.Rect``
    still work identically).
    """
    pygame_module = renderer.pygame
    material = item.material
    width = round(
        abs(item.primitive.size[0] * transform.scale[0] / context.camera.width * context.viewport.width)
    )
    height = round(
        abs(
            item.primitive.size[1]
            * transform.scale[1]
            / context.camera.height
            * context.viewport.height
        )
    )
    width = max(width, 1)
    height = max(height, 1)
    raw_radius = item.primitive.radius or 0.0
    radius = round(
        abs(
            raw_radius
            * max(abs(transform.scale[0]), abs(transform.scale[1]))
            / context.camera.width
            * context.viewport.width
        )
    )
    radius = max(0, min(radius, min(width, height) // 2))
    outline_color: tuple[int, ...] | None = None
    outline_width = 0
    if material.outline is not None and material.outline_width:
        outline_color = renderer._color(modulate_color(material.outline, modulation), material.opacity)
        outline_width = round(material.outline_width)
    angle = transform.rotation - math.degrees(context.camera.rotation)
    if angle:
        surface_factory = getattr(pygame_module, "Surface", None)
        transform_api = getattr(pygame_module, "transform", None)
        if not callable(surface_factory) or not (
            transform_api is not None and callable(getattr(transform_api, "rotate", None))
        ):
            raise RuntimeError("Pygame backend cannot draw rotated rounded rectangles")
        alpha_flag = getattr(pygame_module, "SRCALPHA", 0)
        local = surface_factory((width, height), flags=alpha_flag)
        local_rect = renderer._rect((0, 0, width, height))
        draw.rect(local, color, local_rect, border_radius=radius)
        if outline_color is not None:
            draw.rect(local, outline_color, local_rect, outline_width, border_radius=radius)
        rotated = transform_api.rotate(local, angle)
        get_size = cast(Callable[[], tuple[int, int]] | None, getattr(rotated, "get_size", None))
        rotated_size = get_size() if callable(get_size) else (width, height)
        destination = renderer._rect_from_center(
            position, round(rotated_size[0]), round(rotated_size[1])
        )
        surface.blit(rotated, destination)
    else:
        rectangle = renderer._rect_from_center(position, width, height)
        draw.rect(surface, color, rectangle, border_radius=radius)
        if outline_color is not None:
            draw.rect(surface, outline_color, rectangle, outline_width, border_radius=radius)
