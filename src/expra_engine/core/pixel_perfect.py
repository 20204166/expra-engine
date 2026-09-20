"""Pixel-perfect 2D rendering math.

Inspired by Ursina's pixel_perfect sample and Sprite.ppu concepts.
Backend-neutral: only pure integer-scaling math and letterbox/pillarbox
geometry live here.  No renderer calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ("PixelPerfectSettings", "ScaleResult")


@dataclass(frozen=True)
class ScaleResult:
    """The result of fitting a reference resolution into a target."""

    integer_scale: int
    scaled_width: int
    scaled_height: int
    letterbox_x: int
    letterbox_y: int
    letterbox_width: int
    letterbox_height: int


@dataclass(frozen=True)
class PixelPerfectSettings:
    """Pure settings for pixel-perfect integer scaling.

    ``reference_resolution`` is the logical canvas size (e.g. 320x180).
    ``pixels_per_unit`` relates logical pixels to world units.
    ``nearest_filter`` records the preference for the renderer.

    Calling ``fit(target_width, target_height)`` returns the largest integer
    scale factor that fits the reference inside the target, plus the viewport
    offset for letterboxing/pillarboxing.
    """

    reference_width: int
    reference_height: int
    pixels_per_unit: float = 1.0
    nearest_filter: bool = True

    def __post_init__(self) -> None:
        if self.reference_width <= 0 or self.reference_height <= 0:
            raise ValueError("reference resolution must have positive dimensions")
        if not math.isfinite(self.pixels_per_unit) or self.pixels_per_unit <= 0.0:
            raise ValueError("pixels_per_unit must be finite and positive")

    def fit(self, target_width: int, target_height: int) -> ScaleResult:
        """Return the maximum integer scale that fits inside the target.

        The integer scale is at least 1 even when the target is smaller
        than the reference, so the result is always renderable.
        """
        if target_width <= 0 or target_height <= 0:
            raise ValueError("target dimensions must be positive")
        scale_x = target_width // self.reference_width
        scale_y = target_height // self.reference_height
        scale = max(1, min(scale_x, scale_y))
        scaled_w = self.reference_width * scale
        scaled_h = self.reference_height * scale
        offset_x = (target_width - scaled_w) // 2
        offset_y = (target_height - scaled_h) // 2
        return ScaleResult(
            integer_scale=scale,
            scaled_width=scaled_w,
            scaled_height=scaled_h,
            letterbox_x=offset_x,
            letterbox_y=offset_y,
            letterbox_width=target_width,
            letterbox_height=target_height,
        )
