"""Backend-neutral 2D collider component data."""

from __future__ import annotations

import math
from typing import Any

from expra_engine.core.component import Component

__all__ = ("ColliderComponent",)


def _finite(value: float, name: str) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


class ColliderComponent(Component):
    component_type = "collider"

    def __init__(
        self,
        shape: str = "rectangle",
        width: float = 1.0,
        height: float = 1.0,
        radius: float | None = None,
        offset: tuple[float, float] = (0.0, 0.0),
        solid: bool = True,
        trigger: bool = False,
        enabled: bool = True,
        layer: int = 1,
        mask: int = 0xFFFFFFFF,
    ) -> None:
        super().__init__(enabled=enabled)
        if shape not in {"rectangle", "circle"}:
            raise ValueError("shape must be 'rectangle' or 'circle'")
        self.shape = shape
        self.width = _finite(width, "width")
        self.height = _finite(height, "height")
        self.radius = None if radius is None else _finite(radius, "radius")
        if self.radius is not None and self.radius <= 0.0:
            raise ValueError("radius must be positive")
        if shape == "rectangle" and (self.width <= 0.0 or self.height <= 0.0):
            raise ValueError("rectangle width and height must be positive")
        if shape == "circle" and (self.radius is None or self.radius <= 0.0):
            raise ValueError("circle radius must be positive")
        if len(offset) != 2:
            raise ValueError("offset must contain exactly two values")
        self.offset = (_finite(offset[0], "offset.x"), _finite(offset[1], "offset.y"))
        self.solid = bool(solid)
        self.trigger = bool(trigger)
        self.layer = self._bitfield(layer, "layer")
        self.mask = self._bitfield(mask, "mask")

    @staticmethod
    def _bitfield(value: int, name: str) -> int:
        if isinstance(value, bool) or int(value) != value or int(value) < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return int(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "shape": self.shape,
            "width": self.width,
            "height": self.height,
            "radius": self.radius,
            "offset": list(self.offset),
            "solid": self.solid,
            "trigger": self.trigger,
            "layer": self.layer,
            "mask": self.mask,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColliderComponent:
        return cls(
            shape=data.get("shape", "rectangle"),
            width=data.get("width", 1.0),
            height=data.get("height", 1.0),
            radius=data.get("radius"),
            offset=tuple(data.get("offset", (0.0, 0.0))),
            solid=data.get("solid", True),
            trigger=data.get("trigger", False),
            enabled=data.get("enabled", True),
            layer=data.get("layer", 1),
            mask=data.get("mask", 0xFFFFFFFF),
        )

    @property
    def editor_outline(self) -> dict[str, Any]:
        """Return editor-only outline data without adding preview state to JSON."""
        return {
            "shape": self.shape,
            "width": self.width,
            "height": self.height,
            "radius": self.radius,
            "offset": self.offset,
        }


# Keep metadata available when callers import this component module directly.
from expra_engine.core.component import _register_physics_components

_register_physics_components()
