"""Pure World-space geometry: anchor triggers, bounds, and placement math."""

from __future__ import annotations

import math

from expra_engine.core.scene import Level, WorldTransform2D
from expra_engine.core.world import LevelDescriptor
from expra_engine.runtime.level_anchor import LevelAnchorComponent

__all__ = (
    "_anchor_local_point",
    "_descriptor_world_bounds",
    "_inside_anchor_trigger",
    "_level_world_bounds",
    "_segment_intersects_anchor_trigger",
)


def _anchor_local_point(
    point: tuple[float, float],
    center: tuple[float, float],
    pose: WorldTransform2D,
    marker: LevelAnchorComponent,
) -> tuple[float, float] | None:
    dx, dy = point[0] - center[0], point[1] - center[1]
    angle = math.radians(-pose.rotation)
    local_x = dx * math.cos(angle) - dy * math.sin(angle)
    local_y = dx * math.sin(angle) + dy * math.cos(angle)
    scale_x, scale_y = abs(pose.scale[0]), abs(pose.scale[1])
    if scale_x <= 1e-12 or scale_y <= 1e-12:
        return None
    return (
        local_x / scale_x / (marker.size[0] / 2.0),
        local_y / scale_y / (marker.size[1] / 2.0),
    )


def _inside_anchor_trigger(
    point: tuple[float, float],
    center: tuple[float, float],
    pose: WorldTransform2D,
    marker: LevelAnchorComponent,
) -> bool:
    local = _anchor_local_point(point, center, pose, marker)
    if local is None:
        return False
    local_x, local_y = local
    if marker.shape.value == "circle":
        return local_x**2 + local_y**2 <= 1.0
    return abs(local_x) <= 1.0 and abs(local_y) <= 1.0


def _segment_intersects_anchor_trigger(
    start: tuple[float, float] | None,
    end: tuple[float, float],
    center: tuple[float, float],
    pose: WorldTransform2D,
    marker: LevelAnchorComponent,
) -> bool:
    if start is None:
        return _inside_anchor_trigger(end, center, pose, marker)
    first = _anchor_local_point(start, center, pose, marker)
    second = _anchor_local_point(end, center, pose, marker)
    if first is None or second is None:
        return False
    x0, y0 = first
    dx, dy = second[0] - x0, second[1] - y0
    if marker.shape.value == "circle":
        length_squared = dx * dx + dy * dy
        amount = (
            0.0
            if length_squared <= 1e-24
            else min(1.0, max(0.0, -(x0 * dx + y0 * dy) / length_squared))
        )
        nearest_x, nearest_y = x0 + amount * dx, y0 + amount * dy
        return nearest_x * nearest_x + nearest_y * nearest_y <= 1.0

    minimum, maximum = 0.0, 1.0
    for origin, delta in ((x0, dx), (y0, dy)):
        if abs(delta) <= 1e-12:
            if abs(origin) > 1.0:
                return False
            continue
        first_edge, second_edge = (-1.0 - origin) / delta, (1.0 - origin) / delta
        if first_edge > second_edge:
            first_edge, second_edge = second_edge, first_edge
        minimum = max(minimum, first_edge)
        maximum = min(maximum, second_edge)
        if minimum > maximum:
            return False
    return True


def _descriptor_world_bounds(
    descriptor: LevelDescriptor,
) -> tuple[float, float, float, float] | None:
    if descriptor.bounds is None:
        return None
    x, y, width, height = descriptor.bounds
    return (x, y, x + width, y + height)


def _level_world_bounds(
    level: Level,
    descriptor: LevelDescriptor,
) -> tuple[float, float, float, float] | None:
    explicit = _descriptor_world_bounds(descriptor)
    if explicit is not None:
        return explicit
    local = level.level_metadata.world_bounds
    if local is not None:
        x, y, width, height = local
        return (
            descriptor.origin[0] + x,
            descriptor.origin[1] + y,
            descriptor.origin[0] + x + width,
            descriptor.origin[1] + y + height,
        )
    camera = level.camera
    limits = camera.get("limits")
    if camera.get("limit_enabled") and isinstance(limits, (tuple, list)) and len(limits) == 4:
        left, bottom, right, top = (float(value) for value in limits)
        return (
            descriptor.origin[0] + left,
            descriptor.origin[1] + bottom,
            descriptor.origin[0] + right,
            descriptor.origin[1] + top,
        )
    return None
