"""Small editor overlay drawing helpers kept out of the viewport controller."""

from __future__ import annotations

from typing import Any

from expra_engine.ui.viewport_render_target import ColliderOutline


def draw_collider_overlays(
    canvas: Any,
    colliders: tuple[ColliderOutline, ...],
    camera: Any,
    warning_color: str,
    area_color: str | None = None,
) -> None:
    """Draw a dashed outline per collider; Area entities use ``area_color``.

    ``area_color`` defaults to ``warning_color`` so existing callers that
    don't pass it keep the prior single-color behavior.
    """
    for collider in colliders:
        color = area_color if collider.is_area and area_color is not None else warning_color
        ex, ey = camera.project(collider.position)
        data = collider.outline
        if data["shape"] == "circle":
            radius = float(data["radius"]) * camera._camera.pixel_ratio
            canvas.create_oval(
                ex - radius,
                ey - radius,
                ex + radius,
                ey + radius,
                outline=color,
                dash=(4, 2),
                tags="collider",
            )
        else:
            width = float(data["width"]) * camera._camera.pixel_ratio / 2
            height = float(data["height"]) * camera._camera.pixel_ratio / 2
            canvas.create_rectangle(
                ex - width,
                ey - height,
                ex + width,
                ey + height,
                outline=color,
                dash=(4, 2),
                tags="collider",
            )
