"""Serializable 2D area-field configuration.

AreaComponent describes environmental physics fields attached to an entity.
Geometry and layer/mask filtering remain owned by ColliderComponent, while
PhysicsWorld2D owns overlap detection and effect resolution.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from expra_engine.core.component import Component

__all__ = ("AreaComponent", "SpaceOverride")

Vec2 = tuple[float, float]


class SpaceOverride(str, Enum):
    """How an area field combines with the value already accumulated."""

    DISABLED = "disabled"
    COMBINE = "combine"
    COMBINE_REPLACE = "combine_replace"
    REPLACE = "replace"
    REPLACE_COMBINE = "replace_combine"


def _finite(value: object, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite number")
    return converted


def _non_negative(value: object, name: str) -> float:
    converted = _finite(value, name)
    if converted < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return converted


def _vec2(value: object, name: str) -> Vec2:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain exactly two finite numbers")
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{name} must contain exactly two finite numbers") from exc
    if len(items) != 2:
        raise ValueError(f"{name} must contain exactly two finite numbers")
    return (_finite(items[0], f"{name}.x"), _finite(items[1], f"{name}.y"))


def _mode(value: SpaceOverride | str, name: str) -> SpaceOverride:
    if isinstance(value, SpaceOverride):
        return value
    try:
        return SpaceOverride(str(value))
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in SpaceOverride)
        raise ValueError(f"{name} must be one of: {allowed}") from exc


def _priority(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("priority must be an integer")
    try:
        converted = int(value)
        if float(value) != converted:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("priority must be an integer") from exc
    return converted


class AreaComponent(Component):
    """Environmental gravity and damping fields for a collider volume."""

    component_type = "area"

    def __init__(
        self,
        *,
        priority: int = 0,
        gravity_mode: SpaceOverride | str = SpaceOverride.DISABLED,
        gravity: float = 0.0,
        gravity_direction: Vec2 = (0.0, -1.0),
        gravity_point: bool = False,
        gravity_point_center: Vec2 = (0.0, 0.0),
        gravity_point_unit_distance: float = 0.0,
        linear_damp_mode: SpaceOverride | str = SpaceOverride.DISABLED,
        linear_damp: float = 0.0,
        angular_damp_mode: SpaceOverride | str = SpaceOverride.DISABLED,
        angular_damp: float = 0.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.priority = _priority(priority)
        self.gravity_mode = _mode(gravity_mode, "gravity_mode")
        self.gravity = _finite(gravity, "gravity")
        self.gravity_direction = _vec2(gravity_direction, "gravity_direction")
        self.gravity_point = bool(gravity_point)
        self.gravity_point_center = _vec2(gravity_point_center, "gravity_point_center")
        self.gravity_point_unit_distance = _non_negative(
            gravity_point_unit_distance,
            "gravity_point_unit_distance",
        )
        self.linear_damp_mode = _mode(linear_damp_mode, "linear_damp_mode")
        self.linear_damp = _non_negative(linear_damp, "linear_damp")
        self.angular_damp_mode = _mode(angular_damp_mode, "angular_damp_mode")
        self.angular_damp = _non_negative(angular_damp, "angular_damp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "priority": self.priority,
            "gravity_mode": self.gravity_mode.value,
            "gravity": self.gravity,
            "gravity_direction": list(self.gravity_direction),
            "gravity_point": self.gravity_point,
            "gravity_point_center": list(self.gravity_point_center),
            "gravity_point_unit_distance": self.gravity_point_unit_distance,
            "linear_damp_mode": self.linear_damp_mode.value,
            "linear_damp": self.linear_damp,
            "angular_damp_mode": self.angular_damp_mode.value,
            "angular_damp": self.angular_damp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AreaComponent:
        return cls(
            priority=data.get("priority", 0),
            gravity_mode=data.get("gravity_mode", SpaceOverride.DISABLED.value),
            gravity=data.get("gravity", 0.0),
            gravity_direction=tuple(data.get("gravity_direction", (0.0, -1.0))),
            gravity_point=data.get("gravity_point", False),
            gravity_point_center=tuple(data.get("gravity_point_center", (0.0, 0.0))),
            gravity_point_unit_distance=data.get("gravity_point_unit_distance", 0.0),
            linear_damp_mode=data.get("linear_damp_mode", SpaceOverride.DISABLED.value),
            linear_damp=data.get("linear_damp", 0.0),
            angular_damp_mode=data.get("angular_damp_mode", SpaceOverride.DISABLED.value),
            angular_damp=data.get("angular_damp", 0.0),
            enabled=data.get("enabled", True),
        )


from expra_engine.core.component import _register_physics_components

_register_physics_components()
