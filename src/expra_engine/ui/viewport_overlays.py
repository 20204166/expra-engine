"""Small editor overlay drawing helpers kept out of the viewport controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from expra_engine.ui.viewport_render_target import ColliderOutline


@dataclass(frozen=True)
class ColliderCanvasEntry:
    shape: str
    item_id: int
    color: str


def draw_collider_overlays(
    canvas: Any,
    colliders: tuple[ColliderOutline, ...],
    camera: Any,
    warning_color: str,
    area_color: str | None = None,
    *,
    created_items: list[int] | None = None,
    entries: dict[str, ColliderCanvasEntry] | None = None,
    pan_delta: tuple[float, float] | None = None,
) -> None:
    """Draw a dashed outline per collider; Area entities use ``area_color``.

    ``area_color`` defaults to ``warning_color`` so existing callers that
    don't pass it keep the prior single-color behavior.
    """
    retained = entries is not None
    if entries is None:
        entries = {}
    needed_ids = {collider.entity_id for collider in colliders}
    for stale in set(entries) - needed_ids:
        if retained:
            canvas.delete(entries.pop(stale).item_id)
    for collider in colliders:
        color = area_color if collider.is_area and area_color is not None else warning_color
        ex, ey = camera.project(collider.position)
        data = collider.outline
        if data["shape"] == "circle":
            radius = float(data["radius"]) * camera._camera.pixel_ratio
            shape = "circle"
            coords = (ex - radius, ey - radius, ex + radius, ey + radius)
        else:
            width = float(data["width"]) * camera._camera.pixel_ratio / 2
            height = float(data["height"]) * camera._camera.pixel_ratio / 2
            shape = "rectangle"
            coords = (ex - width, ey - height, ex + width, ey + height)

        existing = entries.get(collider.entity_id) if retained else None
        if existing is not None and existing.shape == shape:
            if pan_delta is None:
                canvas.coords(existing.item_id, *coords)
            if existing.color != color:
                canvas.itemconfig(existing.item_id, outline=color)
                entries[collider.entity_id] = ColliderCanvasEntry(shape, existing.item_id, color)
            continue
        if existing is not None:
            canvas.delete(existing.item_id)
        create = canvas.create_oval if shape == "circle" else canvas.create_rectangle
        item_id = create(
            *coords,
            outline=color,
            dash=(4, 2),
            tags="collider",
            world_layer=True,
        )
        if created_items is not None:
            created_items.append(item_id)
        if retained:
            entries[collider.entity_id] = ColliderCanvasEntry(shape, item_id, color)
