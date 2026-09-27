"""Renderer-neutral authored data for simple 2D local lights."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.rendering import Color

__all__ = ("Light2DComponent",)

_WHITE = Color(1.0, 1.0, 1.0)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _color(value: Color | tuple[float, ...] | list[float]) -> Color:
    if isinstance(value, Color):
        return value
    if isinstance(value, (str, bytes)):
        raise ValueError("color must contain 3 or 4 values")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError("color must contain 3 or 4 values") from exc
    if len(values) not in (3, 4):
        raise ValueError("color must contain 3 or 4 values")
    if any(isinstance(channel, bool) or not isinstance(channel, Real) for channel in values):
        raise ValueError("color channels must be numeric, not bool or text")
    try:
        return Color(*values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("color channels must be finite numbers between 0 and 1") from exc


class Light2DComponent(Component):
    """Opt-in point or cone light attached to an Entity's world transform."""

    component_type = "light_2d"

    def __init__(
        self,
        kind: str = "point",
        color: Color | tuple[float, ...] | list[float] = _WHITE,
        energy: float = 1.0,
        radius: float = 4.0,
        falloff: float = 2.0,
        cone_angle: float = 60.0,
        visible: bool = True,
        *,
        enabled: bool = True,
    ) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a bool")
        if type(visible) is not bool:
            raise ValueError("visible must be a bool")
        super().__init__(enabled=enabled)
        if not isinstance(kind, str) or kind not in {"point", "spot"}:
            raise ValueError("kind must be 'point' or 'spot'")
        self.kind = kind
        self.color = _color(color)
        self.energy = _finite(energy, "energy")
        self.radius = _finite(radius, "radius")
        self.falloff = _finite(falloff, "falloff")
        self.cone_angle = _finite(cone_angle, "cone_angle")
        if not 0.0 <= self.energy <= 8.0:
            raise ValueError("energy must be between 0 and 8")
        if self.radius <= 0.0:
            raise ValueError("radius must be positive")
        if not 0.1 <= self.falloff <= 8.0:
            raise ValueError("falloff must be between 0.1 and 8")
        if not 0.0 < self.cone_angle <= 360.0:
            raise ValueError("cone_angle must be greater than 0 and at most 360")
        self.visible = visible

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "visible": self.visible,
            "kind": self.kind,
            "color": [self.color.red, self.color.green, self.color.blue, self.color.alpha],
            "energy": self.energy,
            "radius": self.radius,
            "falloff": self.falloff,
            "cone_angle": self.cone_angle,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Light2DComponent:
        return cls(
            kind=data.get("kind", "point"),
            color=data.get("color", (1.0, 1.0, 1.0, 1.0)),
            energy=data.get("energy", 1.0),
            radius=data.get("radius", 4.0),
            falloff=data.get("falloff", 2.0),
            cone_angle=data.get("cone_angle", 60.0),
            visible=data.get("visible", True),
            enabled=data.get("enabled", True),
        )
