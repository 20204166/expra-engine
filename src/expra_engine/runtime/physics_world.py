"""Deterministic, broadphase-free 2D physics queries."""

from __future__ import annotations

import math
from dataclasses import dataclass

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.physics import HitResult2D, TriggerEvent

__all__ = ("PhysicsWorld2D",)


@dataclass(frozen=True)
class _Collider:
    entity: Entity
    component: ColliderComponent
    center: tuple[float, float]


class PhysicsWorld2D:
    """Answer deterministic queries over the current scene contents."""

    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self._trigger_pairs: set[tuple[str, str]] = set()
        self._entity_order: dict[str, int] = {}

    def _colliders(self) -> tuple[_Collider, ...]:
        result: list[_Collider] = []
        for index, entity in enumerate(self.scene.entities):
            self._entity_order.setdefault(entity.entity_id, index)
            if not entity.enabled:
                continue
            component = entity.get_component(ColliderComponent)
            if component is None or not component.enabled or not (component.solid or component.trigger):
                continue
            transform = entity.get_component(TransformComponent)
            position = (transform.x, transform.y) if transform is not None else (0.0, 0.0)
            result.append(
                _Collider(
                    entity,
                    component,
                    (position[0] + component.offset[0], position[1] + component.offset[1]),
                )
            )
        return tuple(result)

    @staticmethod
    def _filtered(first: _Collider, second: _Collider) -> bool:
        return bool(
            first.component.mask & second.component.layer
            and second.component.mask & first.component.layer
        )

    @staticmethod
    def _overlaps(first: _Collider, second: _Collider) -> bool:
        a, b = first.component, second.component
        ax, ay = first.center
        bx, by = second.center
        if a.shape == "circle" and b.shape == "circle":
            assert a.radius is not None and b.radius is not None
            return (ax - bx) ** 2 + (ay - by) ** 2 <= (a.radius + b.radius) ** 2
        if a.shape == "rectangle" and b.shape == "rectangle":
            return abs(ax - bx) <= (a.width + b.width) / 2 and abs(ay - by) <= (a.height + b.height) / 2
        circle, rectangle = (first, second) if a.shape == "circle" else (second, first)
        radius = circle.component.radius
        assert radius is not None
        cx, cy = circle.center
        rx, ry = rectangle.center
        closest_x = max(rx - rectangle.component.width / 2, min(cx, rx + rectangle.component.width / 2))
        closest_y = max(ry - rectangle.component.height / 2, min(cy, ry + rectangle.component.height / 2))
        return (cx - closest_x) ** 2 + (cy - closest_y) ** 2 <= radius**2

    def overlap(self, body_id: str, *, include_triggers: bool = True) -> tuple[str, ...]:
        colliders = self._colliders()
        body = next((item for item in colliders if item.entity.entity_id == body_id), None)
        if body is None:
            return ()
        return tuple(
            item.entity.entity_id
            for item in colliders
            if item is not body
            and (include_triggers or not item.component.trigger)
            and self._filtered(body, item)
            and self._overlaps(body, item)
        )

    def raycast(
        self,
        origin: tuple[float, float],
        direction: tuple[float, float],
        distance: float,
        *,
        mask: int = 0xFFFFFFFF,
        include_triggers: bool = True,
    ) -> HitResult2D:
        ox, oy = origin
        dx, dy = direction
        distance = float(distance)
        length = math.hypot(dx, dy)
        if not all(math.isfinite(value) for value in (*origin, *direction, distance)):
            raise ValueError("raycast arguments must be finite")
        if distance < 0.0 or length == 0.0:
            raise ValueError("raycast requires non-negative distance and non-zero direction")
        ux, uy = dx / length, dy / length
        results: list[HitResult2D] = []
        for item in self._colliders():
            if not include_triggers and item.component.trigger:
                continue
            if not item.component.layer & mask:
                continue
            hit_distance, normal = self._ray_shape((ox, oy), (ux, uy), distance, item)
            if hit_distance is None:
                continue
            point = (ox + ux * hit_distance, oy + uy * hit_distance)
            results.append(
                HitResult2D(
                    hit=True,
                    entity_id=item.entity.entity_id,
                    point=point,
                    normal=normal,
                    distance=hit_distance,
                    fraction=hit_distance / distance if distance else 0.0,
                )
            )
        return HitResult2D.nearest(results) or HitResult2D.no_hit()

    @staticmethod
    def _ray_shape(origin, unit, distance, item):
        component = item.component
        cx, cy = item.center
        ox, oy = origin
        ux, uy = unit
        if component.shape == "circle":
            assert component.radius is not None
            vx, vy = cx - ox, cy - oy
            projection = vx * ux + vy * uy
            discriminant = projection * projection - (vx * vx + vy * vy - component.radius**2)
            if discriminant < 0.0:
                return None, None
            hit = projection - math.sqrt(discriminant)
            if hit < 0.0:
                hit = projection + math.sqrt(discriminant)
            if not 0.0 <= hit <= distance:
                return None, None
            px, py = ox + ux * hit, oy + uy * hit
            normal_length = math.hypot(px - cx, py - cy) or 1.0
            return hit, ((px - cx) / normal_length, (py - cy) / normal_length)
        half_x, half_y = component.width / 2, component.height / 2
        t_min, t_max = 0.0, distance
        normal = (0.0, 0.0)
        for coordinate, direction, low, high, axis in (
            (ox, ux, cx - half_x, cx + half_x, 0),
            (oy, uy, cy - half_y, cy + half_y, 1),
        ):
            if direction == 0.0:
                if coordinate < low or coordinate > high:
                    return None, None
                continue
            near, far = (low - coordinate) / direction, (high - coordinate) / direction
            near_normal = (-1.0, 0.0) if axis == 0 else (0.0, -1.0)
            if near > far:
                near, far = far, near
                near_normal = (1.0, 0.0) if axis == 0 else (0.0, 1.0)
            if near > t_min:
                t_min, normal = near, near_normal
            t_max = min(t_max, far)
            if t_min > t_max:
                return None, None
        return t_min, normal

    def step_triggers(self) -> tuple[TriggerEvent, ...]:
        colliders = self._colliders()
        current: set[tuple[str, str]] = set()
        for trigger in colliders:
            if not trigger.component.trigger:
                continue
            for body in colliders:
                if body is trigger or not self._filtered(trigger, body):
                    continue
                if self._overlaps(trigger, body):
                    current.add((trigger.entity.entity_id, body.entity.entity_id))
        events: list[TriggerEvent] = []
        for pair in sorted(
            current | self._trigger_pairs,
            key=lambda p: (self._entity_order.get(p[0], 10**9), self._entity_order.get(p[1], 10**9)),
        ):
            if pair in current:
                phase = "stayed" if pair in self._trigger_pairs else "entered"
            else:
                phase = "exited"
            events.append(TriggerEvent(phase, *pair))
        self._trigger_pairs = current
        return tuple(events)
