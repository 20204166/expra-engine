"""Renderer-neutral visual component data."""

from __future__ import annotations

import math
from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.animation import SpriteRegion
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


def _vec2(value: object, name: str) -> tuple[float, float]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain two finite numbers")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{name} must contain two finite numbers") from exc
    if len(values) != 2:
        raise ValueError(f"{name} must contain two finite numbers")
    return (_finite(values[0], f"{name}.x"), _finite(values[1], f"{name}.y"))


def _region(value: object) -> SpriteRegion | None:
    if value is None or isinstance(value, SpriteRegion):
        return value
    if isinstance(value, (str, bytes)):
        raise ValueError("region must contain x, y, width, height")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("region must contain x, y, width, height") from exc
    if len(values) != 4:
        raise ValueError("region must contain x, y, width, height")
    try:
        numeric = tuple(float(item) for item in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("region must contain integer pixel values") from exc
    if not all(math.isfinite(item) and item.is_integer() for item in numeric):
        raise ValueError("region must contain integer pixel values")
    return SpriteRegion(*(int(item) for item in numeric))


def _region_dict(value: SpriteRegion | None) -> list[int] | None:
    return None if value is None else [value.x, value.y, value.width, value.height]


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
        region: SpriteRegion | tuple[int, ...] | list[int] | None = None,
        centered: bool = True,
        offset: tuple[float, float] | list[float] = (0.0, 0.0),
        flip_h: bool = False,
        flip_v: bool = False,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.asset = str(asset)
        self.tint = _color(tint)
        self.width = _finite(width, "width")
        self.height = _finite(height, "height")
        self.region = region
        self.centered = bool(centered)
        self.offset = _vec2(offset, "offset")
        self.flip_h = bool(flip_h)
        self.flip_v = bool(flip_v)
        self.layer = int(layer)
        self.visible = bool(visible)

    @property
    def region(self) -> SpriteRegion | None:
        return self._region

    @region.setter
    def region(self, value: object) -> None:
        self._region = _region(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "asset": self.asset,
            "tint": _color_dict(self.tint),
            "width": self.width,
            "height": self.height,
            "region": _region_dict(self.region),
            "centered": self.centered,
            "offset": list(self.offset),
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
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
            region=data.get("region"),
            centered=data.get("centered", True),
            offset=data.get("offset", (0.0, 0.0)),
            flip_h=data.get("flip_h", False),
            flip_v=data.get("flip_v", False),
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
