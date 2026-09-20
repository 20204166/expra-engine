"""Immutable, renderer-neutral nine-slice patch geometry."""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Insets, Rect

__all__ = ("NineSlice", "NineSlicePatch")


@dataclass(frozen=True)
class NineSlicePatch:
    """A named logical rectangle in a nine-slice layout."""

    name: str
    rect: Rect


@dataclass(frozen=True)
class NineSlice:
    """Describe fixed edge widths and resolve them into nine logical patches.

    ``outset`` expands the resolved panel. ``padding`` reserves additional
    fixed space on each edge before the center patch is calculated.
    """

    borders: Insets
    outset: Insets = field(default_factory=Insets)
    padding: Insets = field(default_factory=Insets)

    def resolve(self, panel: Rect) -> tuple[NineSlicePatch, ...]:
        outer = Rect(
            panel.x - self.outset.left,
            panel.y - self.outset.bottom,
            panel.width + self.outset.left + self.outset.right,
            panel.height + self.outset.top + self.outset.bottom,
        )
        left = min(self.borders.left + self.padding.left, outer.width / 2.0)
        right = min(self.borders.right + self.padding.right, outer.width / 2.0)
        bottom = min(self.borders.bottom + self.padding.bottom, outer.height / 2.0)
        top = min(self.borders.top + self.padding.top, outer.height / 2.0)

        x0 = outer.x
        x1 = x0 + left
        x2 = outer.x + outer.width - right
        x3 = outer.x + outer.width
        y0 = outer.y
        y1 = y0 + bottom
        y2 = outer.y + outer.height - top
        y3 = outer.y + outer.height

        return (
            NineSlicePatch("bottom_left", Rect(x0, y0, x1 - x0, y1 - y0)),
            NineSlicePatch("bottom", Rect(x1, y0, x2 - x1, y1 - y0)),
            NineSlicePatch("bottom_right", Rect(x2, y0, x3 - x2, y1 - y0)),
            NineSlicePatch("left", Rect(x0, y1, x1 - x0, y2 - y1)),
            NineSlicePatch("center", Rect(x1, y1, x2 - x1, y2 - y1)),
            NineSlicePatch("right", Rect(x2, y1, x3 - x2, y2 - y1)),
            NineSlicePatch("top_left", Rect(x0, y2, x1 - x0, y3 - y2)),
            NineSlicePatch("top", Rect(x1, y2, x2 - x1, y3 - y2)),
            NineSlicePatch("top_right", Rect(x2, y2, x3 - x2, y3 - y2)),
        )
