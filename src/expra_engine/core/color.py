"""Immutable, renderer-neutral RGBA color type.

Adapted from Ursina's color.py concepts (MIT License, Pokepetter/ursina).
No Panda3D Vec4 inheritance; no mutable-global palette.

All channel values are float in [0.0, 1.0]; alpha defaults to 1.0 (opaque).
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass

__all__ = ("Color",)


def _clamp01(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return max(0.0, min(1.0, v))


@dataclass(frozen=True)
class Color:
    """An immutable RGBA colour; all channels are floats in [0, 1].

    Channels are clamped on construction; no exception for out-of-range values
    because blending, tinting, and shading routinely produce temporary
    intermediate values outside [0, 1].
    """

    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "r", _clamp01(self.r, "r"))
        object.__setattr__(self, "g", _clamp01(self.g, "g"))
        object.__setattr__(self, "b", _clamp01(self.b, "b"))
        object.__setattr__(self, "a", _clamp01(self.a, "a"))

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    @property
    def rgba8(self) -> tuple[int, int, int, int]:
        """Return (r, g, b, a) as 8-bit unsigned integers [0, 255]."""
        return (
            round(self.r * 255),
            round(self.g * 255),
            round(self.b * 255),
            round(self.a * 255),
        )

    @property
    def hsv(self) -> tuple[float, float, float]:
        """Return (hue [0,1], saturation [0,1], value [0,1])."""
        return colorsys.rgb_to_hsv(self.r, self.g, self.b)

    def with_alpha(self, alpha: float) -> Color:
        return Color(self.r, self.g, self.b, alpha)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @staticmethod
    def from_rgba8(r: int, g: int, b: int, a: int = 255) -> Color:
        """Construct from 8-bit RGBA channels [0, 255]."""
        return Color(r / 255.0, g / 255.0, b / 255.0, a / 255.0)

    @staticmethod
    def from_hsv(h: float, s: float, v: float, a: float = 1.0) -> Color:
        """Construct from HSV (hue in [0, 1]) + alpha."""
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, float(s), float(v))
        return Color(r, g, b, a)

    @staticmethod
    def from_hex(value: str) -> Color:
        """Parse a hex colour string.

        Accepted forms: ``#RGB``, ``#RRGGBB``, ``#RGBA``, ``#RRGGBBAA``,
        each with or without the leading ``#``.
        """
        raw = value.lstrip("#").strip()
        length = len(raw)
        try:
            if length == 3:
                r, g, b = (int(c * 2, 16) for c in raw)
                return Color(r / 255.0, g / 255.0, b / 255.0)
            if length == 4:
                r, g, b, a = (int(c * 2, 16) for c in raw)
                return Color(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
            if length == 6:
                r = int(raw[0:2], 16)
                g = int(raw[2:4], 16)
                b = int(raw[4:6], 16)
                return Color(r / 255.0, g / 255.0, b / 255.0)
            if length == 8:
                r = int(raw[0:2], 16)
                g = int(raw[2:4], 16)
                b = int(raw[4:6], 16)
                a = int(raw[6:8], 16)
                return Color(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        except ValueError as exc:
            raise ValueError(f"invalid hex colour string: {value!r}") from exc
        raise ValueError(f"invalid hex colour length ({length}) in: {value!r}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def lerp(self, other: Color, t: float) -> Color:
        """Linearly interpolate to *other* at factor *t* [0, 1]."""
        t = float(t)
        if not math.isfinite(t):
            raise ValueError("lerp factor must be finite")

        def mix(a: float, b: float) -> float:
            return a + (b - a) * t

        return Color(
            mix(self.r, other.r), mix(self.g, other.g), mix(self.b, other.b), mix(self.a, other.a)
        )

    def tint(self, amount: float) -> Color:
        """Lighten toward white by *amount* [0, 1]."""
        a = float(amount)
        return Color(
            self.r + (1.0 - self.r) * a,
            self.g + (1.0 - self.g) * a,
            self.b + (1.0 - self.b) * a,
            self.a,
        )

    def shade(self, amount: float) -> Color:
        """Darken toward black by *amount* [0, 1]."""
        a = float(amount)
        return Color(self.r * (1.0 - a), self.g * (1.0 - a), self.b * (1.0 - a), self.a)

    def __repr__(self) -> str:
        return f"Color(r={self.r:.3f}, g={self.g:.3f}, b={self.b:.3f}, a={self.a:.3f})"
