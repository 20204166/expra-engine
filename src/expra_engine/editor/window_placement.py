"""Save and restore editor window geometry."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HIERARCHY_WIDTH_RATIO = 0.30
_HIERARCHY_DEFAULT_MIN_WIDTH = 360
_HIERARCHY_DEFAULT_MAX_WIDTH = 500
_HIERARCHY_MIN_WIDTH = 190
_INSPECTOR_MIN_WIDTH = 260
_VIEWPORT_MIN_WIDTH = 260


def initial_hierarchy_width(content_width: int) -> int:
    """Choose a responsive startup width for the editor's left navigation pane."""
    available = max(
        _HIERARCHY_MIN_WIDTH,
        content_width - _INSPECTOR_MIN_WIDTH - _VIEWPORT_MIN_WIDTH,
    )
    preferred = round(content_width * _HIERARCHY_WIDTH_RATIO)
    return min(
        max(_HIERARCHY_DEFAULT_MIN_WIDTH, preferred),
        _HIERARCHY_DEFAULT_MAX_WIDTH,
        available,
    )


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    width: int
    height: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("window dimensions must be positive")

    def to_geometry_string(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    @classmethod
    def from_geometry_string(cls, geometry: str) -> WindowGeometry | None:
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geometry)
        if match is None:
            return None
        try:
            return cls(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
        except ValueError:
            return None


__all__ = ["WindowGeometry", "initial_hierarchy_width"]
