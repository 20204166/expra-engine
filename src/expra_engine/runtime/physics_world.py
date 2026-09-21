"""Deterministic, broadphase-free 2D physics queries."""

from __future__ import annotations

import math
from dataclasses import dataclass

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.area import AreaComponent, SpaceOverride
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.physics import AreaEffect2D, HitResult2D, TriggerEvent

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

    def _colliders(self, *, include_area_volumes: bool = False) -> tuple[_Collider, ...]:
        result: list[_Collider] = []
        for index, entity in enumerate(self.scene.entities):
            self._entity_order.setdefault(entity.entity_id, index)
            if not entity.enabled:
                continue
            component = entity.get_component(ColliderComponent)
            area = entity.get_component(AreaComponent)
            if component is None or not component.enabled or (
                not (component.solid or component.trigger)
                and not (include_area_volumes and area is not None and area.enabled)
            ):
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

    @staticmethod
    def _apply_vector(
        current: tuple[float, float], value: tuple[float, float], mode: SpaceOverride
    ) -> tuple[tuple[float, float], bool]:
        if mode is SpaceOverride.DISABLED:
            return current, True
        if mode in {SpaceOverride.REPLACE, SpaceOverride.REPLACE_COMBINE}:
            result = value
        else:
            result = (current[0] + value[0], current[1] + value[1])
        return result, mode in {SpaceOverride.COMBINE, SpaceOverride.REPLACE_COMBINE}

    @staticmethod
    def _apply_scalar(current: float, value: float, mode: SpaceOverride) -> tuple[float, bool]:
        if mode is SpaceOverride.DISABLED:
            return current, True
        result = value if mode in {SpaceOverride.REPLACE, SpaceOverride.REPLACE_COMBINE} else current + value
        return result, mode in {SpaceOverride.COMBINE, SpaceOverride.REPLACE_COMBINE}

    @staticmethod
    def _area_gravity(area_item: _Collider, body: _Collider, area: AreaComponent) -> tuple[float, float]:
        if not area.gravity_point:
            return (
                area.gravity * area.gravity_direction[0],
                area.gravity * area.gravity_direction[1],
            )
        area_transform = area_item.entity.get_component(TransformComponent)
        body_transform = body.entity.get_component(TransformComponent)
        area_position = (area_item.center[0], area_item.center[1])
        body_position = body.center
        if area_transform is not None:
            angle = math.radians(area_transform.rotation)
            local_x, local_y = area.gravity_point_center
            area_position = (
                area_transform.x + local_x * math.cos(angle) - local_y * math.sin(angle),
                area_transform.y + local_x * math.sin(angle) + local_y * math.cos(angle),
            )
        if body_transform is not None:
            body_position = (body_transform.x, body_transform.y)
        dx, dy = area_position[0] - body_position[0], area_position[1] - body_position[1]
        distance = math.hypot(dx, dy)
        if distance == 0.0:
            return (0.0, 0.0)
        scale = 1.0
        if area.gravity_point_unit_distance > 0.0:
            scale = (area.gravity_point_unit_distance / distance) ** 2
        magnitude = area.gravity * scale / distance
        return (dx * magnitude, dy * magnitude)

    def resolve_area_effect(
        self,
        body_id: str,
        *,
        gravity: tuple[float, float] = (0.0, 0.0),
        linear_damp: float = 0.0,
        angular_damp: float = 0.0,
    ) -> AreaEffect2D:
        """Resolve active area fields affecting one collider-backed entity."""
        if len(gravity) != 2 or not all(math.isfinite(float(value)) for value in gravity):
            raise ValueError("gravity must contain two finite numbers")
        base_linear = float(linear_damp)
        base_angular = float(angular_damp)
        if not all(math.isfinite(value) and value >= 0.0 for value in (base_linear, base_angular)):
            raise ValueError("damping values must be finite and non-negative")
        colliders = self._colliders(include_area_volumes=True)
        body = next((item for item in colliders if item.entity.entity_id == body_id), None)
        if body is None:
            return AreaEffect2D(gravity=(float(gravity[0]), float(gravity[1])), linear_damp=base_linear, angular_damp=base_angular)
        candidates: list[tuple[_Collider, AreaComponent]] = []
        for item in colliders:
            area = item.entity.get_component(AreaComponent)
            if area is None or not area.enabled or not self._filtered(item, body) or not self._overlaps(item, body):
                continue
            candidates.append((item, area))
        candidates.sort(key=lambda pair: (-pair[1].priority, self._entity_order[pair[0].entity.entity_id]))
        resolved_gravity = (float(gravity[0]), float(gravity[1]))
        resolved_linear = base_linear
        resolved_angular = base_angular
        gravity_active = linear_active = angular_active = True
        area_ids: list[str] = []
        for item, area in candidates:
            area_ids.append(item.entity.entity_id)
            if gravity_active:
                resolved_gravity, gravity_active = self._apply_vector(
                    resolved_gravity,
                    self._area_gravity(item, body, area),
                    area.gravity_mode,
                )
            if linear_active:
                resolved_linear, linear_active = self._apply_scalar(
                    resolved_linear, area.linear_damp, area.linear_damp_mode
                )
            if angular_active:
                resolved_angular, angular_active = self._apply_scalar(
                    resolved_angular, area.angular_damp, area.angular_damp_mode
                )
        return AreaEffect2D(
            gravity=resolved_gravity,
            linear_damp=resolved_linear,
            angular_damp=resolved_angular,
            area_ids=tuple(area_ids),
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
