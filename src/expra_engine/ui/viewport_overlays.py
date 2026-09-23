"""Small editor overlay drawing helpers kept out of the viewport controller."""

from __future__ import annotations

from typing import Any

from expra_engine.ui.viewport_render_target import ColliderOutline


def draw_collider_overlays(
    canvas: Any,
    colliders: tuple[ColliderOutline, ...],
    camera: Any,
    warning_color: str,
) -> None:
    for collider in colliders:
        ex, ey = camera.project(collider.position)
        data = collider.outline
        if data["shape"] == "circle":
            radius = float(data["radius"]) * camera._camera.pixel_ratio
            canvas.create_oval(
                ex - radius,
                ey - radius,
                ex + radius,
                ey + radius,
                outline=warning_color,
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
                outline=warning_color,
                dash=(4, 2),
                tags="collider",
            )
