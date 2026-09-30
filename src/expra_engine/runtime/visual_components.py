"""Renderer-neutral visual component data."""

from __future__ import annotations

import math
from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.validation import finite_float as _finite
from expra_engine.runtime.validation import pair_values

__all__ = ("PrimitiveComponent", "SpriteComponent", "TextComponent")


def _vec2(value: object, name: str) -> tuple[float, float]:
    x, y = pair_values(value, name)
    return (_finite(x, f"{name}.x"), _finite(y, f"{name}.y"))


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


def _normalize_points(
    value: tuple[tuple[float, float], ...] | list[tuple[float, float]] | None,
) -> tuple[tuple[float, float], ...] | None:
    """Normalize polygon points to a tuple of finite (x, y) pairs, or ``None``."""
    if value is None:
        return None
    try:
        raw = tuple(value)
    except TypeError as exc:
        raise ValueError("polygon points must be a sequence of (x, y) pairs") from exc
    normalized: list[tuple[float, float]] = []
    for point in raw:
        try:
            x, y = pair_values(point, "points")
        except (TypeError, ValueError) as exc:
            raise ValueError("each polygon point must be an (x, y) pair") from exc
        normalized.append((_finite(x, "points.x"), _finite(y, "points.y")))
    return tuple(normalized)


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
        points: tuple[tuple[float, float], ...] | list[tuple[float, float]] | None = None,
        thickness: float = 1.0,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.kind = str(kind)
        self.width = _finite(width, "width")
        self.height = _finite(height, "height")
        self.radius = None if radius is None else _finite(radius, "radius")
        self.fill = fill  # goes through property setter
        self.outline = outline  # goes through property setter
        self.outline_width = _finite(outline_width, "outline_width")
        self.layer = int(layer)
        self.visible = bool(visible)
        self.points = _normalize_points(points)
        self.thickness = _finite(thickness, "thickness")
        if self.kind == "polygon" and (self.points is None or len(self.points) < 3):
            raise ValueError("polygon primitive requires at least three points")
        if self.kind == "line":
            if self.points is None or len(self.points) != 2:
                raise ValueError("line primitive requires exactly two points")
            if self.thickness <= 0:
                raise ValueError("line thickness must be positive")

    @property
    def fill(self) -> Color:
        return self._fill

    @fill.setter
    def fill(self, value: Color | tuple[float, ...] | list[float]) -> None:
        self._fill = Color.from_value(value)

    @property
    def outline(self) -> Color | None:
        return self._outline

    @outline.setter
    def outline(self, value: Color | tuple[float, ...] | list[float] | None) -> None:
        self._outline = None if value is None else Color.from_value(value)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.component_type,
            "enabled": self.enabled,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "radius": self.radius,
            "fill": self.fill.to_list(),
            "outline": None if self.outline is None else self.outline.to_list(),
            "outline_width": self.outline_width,
            "layer": self.layer,
            "visible": self.visible,
        }
        if self.points is not None:
            data["points"] = [[x, y] for x, y in self.points]
        if self.thickness != 1.0:
            data["thickness"] = self.thickness
        return data

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
            points=data.get("points"),
            thickness=data.get("thickness", 1.0),
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
        self.tint = Color.from_value(tint)
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
            "tint": self.tint.to_list(),
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
        self.color = Color.from_value(color)
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
            "color": self.color.to_list(),
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
