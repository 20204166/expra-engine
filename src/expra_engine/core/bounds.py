"""Immutable axis-aligned two-dimensional bounds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bounds2D:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.min_x > self.max_x:
            raise ValueError("min_x must be <= max_x")
        if self.min_y > self.max_y:
            raise ValueError("min_y must be <= max_y")

    @classmethod
    def from_center_size(cls, cx: float, cy: float, width: float, height: float) -> Bounds2D:
        half_width, half_height = width / 2.0, height / 2.0
        return cls(
            cx - half_width,
            cy - half_height,
            cx + half_width,
            cy + half_height,
        )

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2.0

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2.0

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def intersects(self, other: Bounds2D) -> bool:
        return (
            self.min_x < other.max_x
            and self.max_x > other.min_x
            and self.min_y < other.max_y
            and self.max_y > other.min_y
        )

    def expand(self, amount: float) -> Bounds2D:
        return Bounds2D(
            self.min_x - amount,
            self.min_y - amount,
            self.max_x + amount,
            self.max_y + amount,
        )


__all__ = ["Bounds2D"]
