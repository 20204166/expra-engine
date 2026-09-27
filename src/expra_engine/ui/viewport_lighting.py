"""Retained Canvas gizmo for the currently selected Light2D component."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from expra_engine.core.scene import Scene
from expra_engine.runtime.lighting_2d import Light2DComponent

__all__ = ("LightGizmo", "update_light_gizmo")


@dataclass
class LightGizmo:
    entity_id: str
    kind: str
    items: tuple[int, ...]


def update_light_gizmo(
    canvas: Any,
    scene: Scene | None,
    selected_id: str | None,
    camera: Any,
    colors: dict[str, str],
    current: LightGizmo | None,
) -> LightGizmo | None:
    """Create once, then move/recolour a small set of selected-light overlays."""
    entity = scene.find_entity(selected_id) if scene is not None and selected_id else None
    light = entity.get_component(Light2DComponent) if entity is not None else None
    if entity is None or light is None:
        if current is not None:
            for item in current.items:
                canvas.delete(item)
        return None

    if current is None or current.entity_id != entity.entity_id or current.kind != light.kind:
        if current is not None:
            for item in current.items:
                canvas.delete(item)
        ids = [
            canvas.create_oval(0, 0, 0, 0, fill="", outline=colors["accent"], dash=(4, 3)),
            canvas.create_oval(0, 0, 0, 0, fill=colors["accent"], outline=colors["accent_ink"]),
        ]
        if light.kind == "spot":
            ids.extend(
                canvas.create_line(0, 0, 0, 0, fill=colors["accent"], dash=(4, 3))
                for _ in range(2)
            )
        current = LightGizmo(entity.entity_id, light.kind, tuple(ids))

    try:
        pose = scene.world_transform(entity.entity_id)  # type: ignore[union-attr]
    except (KeyError, TypeError, ValueError):
        for item in current.items:
            canvas.delete(item)
        return None
    center = camera.project(pose.position)
    radius = light.radius * max(abs(pose.scale[0]), abs(pose.scale[1]))
    radius_edge = camera.project((pose.position[0] + radius, pose.position[1]))
    radius_pixels = math.hypot(radius_edge[0] - center[0], radius_edge[1] - center[1])
    canvas.coords(
        current.items[0],
        center[0] - radius_pixels,
        center[1] - radius_pixels,
        center[0] + radius_pixels,
        center[1] + radius_pixels,
    )
    canvas.coords(
        current.items[1],
        center[0] - 3,
        center[1] - 3,
        center[0] + 3,
        center[1] + 3,
    )
    canvas.itemconfig(current.items[0], outline=colors["accent"])
    canvas.itemconfig(current.items[1], fill=colors["accent"])
    if light.kind == "spot":
        rotation = math.radians(pose.rotation)
        half_cone = math.radians(light.cone_angle / 2)
        for item_id, angle in zip(
            current.items[2:], (rotation - half_cone, rotation + half_cone), strict=True
        ):
            edge = (
                pose.position[0] + radius * math.cos(angle),
                pose.position[1] + radius * math.sin(angle),
            )
            canvas.coords(item_id, *center, *camera.project(edge))
            canvas.itemconfig(item_id, fill=colors["accent"])
    return current
