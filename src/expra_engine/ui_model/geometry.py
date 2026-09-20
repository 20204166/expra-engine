"""Immutable, renderer-neutral UI rectangle layout geometry."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

__all__ = ("Insets", "Rect", "RectTransform")

Vec2 = tuple[float, float]


def _vec2(value: Vec2, name: str) -> Vec2:
    result = (float(value[0]), float(value[1]))
    if not all(isfinite(component) for component in result):
        raise ValueError(f"{name} must contain finite values")
    return result


def _nonnegative_vec2(value: Vec2, name: str) -> Vec2:
    result = _vec2(value, name)
    if result[0] < 0.0 or result[1] < 0.0:
        raise ValueError(f"{name} must not contain negative values")
    return result


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in logical coordinates."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (float(self.x), float(self.y), float(self.width), float(self.height))
        if not all(isfinite(value) for value in values):
            raise ValueError("rectangle values must be finite")
        if values[2] < 0.0 or values[3] < 0.0:
            raise ValueError("rectangle dimensions must not be negative")
        object.__setattr__(self, "x", values[0])
        object.__setattr__(self, "y", values[1])
        object.__setattr__(self, "width", values[2])
        object.__setattr__(self, "height", values[3])


@dataclass(frozen=True)
class Insets:
    """Nonnegative left, top, right, and bottom safe-area insets."""

    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    def __post_init__(self) -> None:
        values = _nonnegative_vec2((self.left, self.top), "safe-area insets") + _nonnegative_vec2(
            (self.right, self.bottom), "safe-area insets"
        )
        object.__setattr__(self, "left", values[0])
        object.__setattr__(self, "top", values[1])
        object.__setattr__(self, "right", values[2])
        object.__setattr__(self, "bottom", values[3])


@dataclass(frozen=True)
class RectTransform:
    """Layout intent resolved against a parent rectangle.

    ``size=None`` stretches between the two normalized anchors. Otherwise the
    size is fixed. ``offset_min`` moves the lower/left edge or fixed anchor;
    ``offset_max`` is an inset from the upper/right edge when stretched.
    """

    anchor_min: Vec2 = (0.0, 0.0)
    anchor_max: Vec2 = (0.0, 0.0)
    pivot: Vec2 = (0.0, 0.0)
    offset_min: Vec2 = (0.0, 0.0)
    offset_max: Vec2 = (0.0, 0.0)
    size: Vec2 | None = None
    min_size: Vec2 = (0.0, 0.0)
    max_size: Vec2 | None = None

    def __post_init__(self) -> None:
        anchor_min = _vec2(self.anchor_min, "anchor_min")
        anchor_max = _vec2(self.anchor_max, "anchor_max")
        pivot = _vec2(self.pivot, "pivot")
        for name, value in (("anchor_min", anchor_min), ("anchor_max", anchor_max), ("pivot", pivot)):
            if not all(0.0 <= component <= 1.0 for component in value):
                raise ValueError(f"{name} must be normalized to [0, 1]")
        if anchor_min[0] > anchor_max[0] or anchor_min[1] > anchor_max[1]:
            raise ValueError("anchor_min must not exceed anchor_max")

        offset_min = _vec2(self.offset_min, "offset_min")
        offset_max = _vec2(self.offset_max, "offset_max")
        size = None if self.size is None else _nonnegative_vec2(self.size, "size")
        min_size = _nonnegative_vec2(self.min_size, "min_size")
        max_size: Vec2 | None = (
            None if self.max_size is None else _nonnegative_vec2(self.max_size, "max_size")
        )
        if max_size is not None and (min_size[0] > max_size[0] or min_size[1] > max_size[1]):
            raise ValueError("min_size must not exceed max_size")

        for name, value in (
            ("anchor_min", anchor_min),
            ("anchor_max", anchor_max),
            ("pivot", pivot),
            ("offset_min", offset_min),
            ("offset_max", offset_max),
            ("min_size", min_size),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "max_size", max_size)

    def resolve(
        self,
        parent: Rect,
        *,
        safe_area: Insets | None = None,
        reference_resolution: Vec2 | None = None,
        dpi_scale: float = 1.0,
    ) -> Rect:
        """Resolve this intent into a logical rectangle without renderer state."""
        dpi = float(dpi_scale)
        if not isfinite(dpi) or dpi <= 0.0:
            raise ValueError("dpi_scale must be positive and finite")
        logical_parent = Rect(parent.x / dpi, parent.y / dpi, parent.width / dpi, parent.height / dpi)
        safe_area = Insets() if safe_area is None else safe_area
        insets = Insets(
            safe_area.left / dpi,
            safe_area.top / dpi,
            safe_area.right / dpi,
            safe_area.bottom / dpi,
        )
        if insets.left + insets.right > logical_parent.width or insets.top + insets.bottom > logical_parent.height:
            raise ValueError("safe-area insets invert the parent rectangle")
        available = Rect(
            logical_parent.x + insets.left,
            logical_parent.y + insets.top,
            logical_parent.width - insets.left - insets.right,
            logical_parent.height - insets.top - insets.bottom,
        )

        scale = (1.0, 1.0)
        if reference_resolution is not None:
            reference = _nonnegative_vec2(reference_resolution, "reference_resolution")
            if reference[0] == 0.0 or reference[1] == 0.0:
                raise ValueError("reference_resolution must be positive")
            scale = (available.width / reference[0], available.height / reference[1])

        offset_min = (self.offset_min[0] * scale[0], self.offset_min[1] * scale[1])
        offset_max = (self.offset_max[0] * scale[0], self.offset_max[1] * scale[1])
        minimum = (self.min_size[0] * scale[0], self.min_size[1] * scale[1])
        maximum = None if self.max_size is None else (self.max_size[0] * scale[0], self.max_size[1] * scale[1])
        if self.size is None:
            start = (
                available.x + available.width * self.anchor_min[0] + offset_min[0],
                available.y + available.height * self.anchor_min[1] + offset_min[1],
            )
            end = (
                available.x + available.width * self.anchor_max[0] - offset_max[0],
                available.y + available.height * self.anchor_max[1] - offset_max[1],
            )
            width, height = end[0] - start[0], end[1] - start[1]
            x, y = start
        else:
            width = self.size[0] * scale[0]
            height = self.size[1] * scale[1]
            anchor = (
                available.x + available.width * self.anchor_min[0] + offset_min[0],
                available.y + available.height * self.anchor_min[1] + offset_min[1],
            )

        width = max(minimum[0], width)
        height = max(minimum[1], height)
        if maximum is not None:
            width = min(maximum[0], width)
            height = min(maximum[1], height)
        if self.size is not None:
            x = anchor[0] - width * self.pivot[0]
            y = anchor[1] - height * self.pivot[1]
        return Rect(x, y, width, height)
