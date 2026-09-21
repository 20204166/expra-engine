"""Renderer-neutral visual component data."""

from __future__ import annotations

import math
from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.rendering import Color

__all__ = ("PrimitiveComponent", "SpriteComponent", "TextComponent")


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _color(value: Color | tuple[float, ...] | list[float]) -> Color:
    if isinstance(value, Color):
        return value
    values = tuple(value)
    if len(values) not in (3, 4):
        raise ValueError("color must contain 3 or 4 values")
    return Color(*values)


def _color_dict(value: Color | None) -> list[float] | None:
    if value is None:
        return None
    return [value.red, value.green, value.blue, value.alpha]


class PrimitiveComponent(Component):
    component_type = "primitive"

    def __init__(
        self,
        kind: str = "rectangle",
        width: float = 1.0,
        height: float = 1.0,
        radius: float | None = None,
        fill: Color | tuple[float, ...] | list[float] = Color(1.0, 1.0, 1.0),
        outline: Color | tuple[float, ...] | list[float] | None = None,
        outline_width: float = 0.0,
        layer: int = 0,
        visible: bool = True,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.kind = str(kind)
        self.width = _finite(width, "width")
        self.height = _finite(height, "height")
        self.radius = None if radius is None else _finite(radius, "radius")
        self.fill = _color(fill)
        self.outline = None if outline is None else _color(outline)
        self.outline_width = _finite(outline_width, "outline_width")
        self.layer = int(layer)
        self.visible = bool(visible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "radius": self.radius,
            "fill": _color_dict(self.fill),
            "outline": _color_dict(self.outline),
            "outline_width": self.outline_width,
            "layer": self.layer,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimitiveComponent:
        return cls(
            kind=data.get("kind", "rectangle"),
            width=data.get("width", 1.0),
            height=data.get("height", 1.0),
            radius=data.get("radius"),
            fill=data.get("fill", (1.0, 1.0, 1.0, 1.0)),
            outline=data.get("outline"),
            outline_width=data.get("outline_width", 0.0),
            layer=data.get("layer", 0),
            visible=data.get("visible", True),
            enabled=data.get("enabled", True),
        )


class SpriteComponent(Component):
    component_type = "sprite"

    def __init__(
        self,
        asset: str = "",
        tint: Color | tuple[float, ...] | list[float] = Color(1.0, 1.0, 1.0),
        width: float = 1.0,
        height: float = 1.0,
        layer: int = 0,
        visible: bool = True,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.asset = str(asset)
        self.tint = _color(tint)
        self.width = _finite(width, "width")
        self.height = _finite(height, "height")
        self.layer = int(layer)
        self.visible = bool(visible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "asset": self.asset,
            "tint": _color_dict(self.tint),
            "width": self.width,
            "height": self.height,
            "layer": self.layer,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpriteComponent:
        return cls(
            asset=data.get("asset", ""),
            tint=data.get("tint", (1.0, 1.0, 1.0, 1.0)),
            width=data.get("width", 1.0),
            height=data.get("height", 1.0),
            layer=data.get("layer", 0),
            visible=data.get("visible", True),
            enabled=data.get("enabled", True),
        )


class TextComponent(Component):
    component_type = "text"

    def __init__(
        self,
        text: str = "",
        font: str = "default",
        size: float = 16.0,
        color: Color | tuple[float, ...] | list[float] = Color(1.0, 1.0, 1.0),
        max_width: float | None = None,
        align: str = "left",
        layer: int = 0,
        visible: bool = True,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.text = str(text)
        self.font = str(font)
        self.size = _finite(size, "size")
        self.color = _color(color)
        self.max_width = None if max_width is None else _finite(max_width, "max_width")
        self.align = str(align)
        self.layer = int(layer)
        self.visible = bool(visible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "text": self.text,
            "font": self.font,
            "size": self.size,
            "color": _color_dict(self.color),
            "max_width": self.max_width,
            "align": self.align,
            "layer": self.layer,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextComponent:
        return cls(
            text=data.get("text", ""),
            font=data.get("font", "default"),
            size=data.get("size", 16.0),
            color=data.get("color", (1.0, 1.0, 1.0, 1.0)),
            max_width=data.get("max_width"),
            align=data.get("align", "left"),
            layer=data.get("layer", 0),
            visible=data.get("visible", True),
            enabled=data.get("enabled", True),
        )


from expra_engine.core.component import _register_visual_components

_register_visual_components()
