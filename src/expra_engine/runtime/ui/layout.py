"""Pure runtime UI layout contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace

from expra_engine.ui_model.geometry import Insets, Rect, RectTransform



@dataclass(frozen=True)
class LayoutSpec(RectTransform):
    """RectTransform with an optional preferred size for intrinsic controls."""

    preferred_size: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.preferred_size is not None:
            preferred = RectTransform(size=self.preferred_size).size
            object.__setattr__(self, "preferred_size", preferred)

    def resolve(self, parent: Rect, **kwargs: object) -> Rect:
        if self.size is None and self.preferred_size is not None:
            return replace(self, size=self.preferred_size).resolve(parent, **kwargs)
        return super().resolve(parent, **kwargs)


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int

    def __post_init__(self) -> None:
        if type(self.width) is not int or type(self.height) is not int:
            raise ValueError("viewport dimensions must be integers")
        if self.width < 0 or self.height < 0:
            raise ValueError("viewport dimensions must not be negative")


@dataclass(frozen=True)
class LayoutResult:
    """Resolved rectangles keyed by stable UI element names."""

    rectangles: dict[str, Rect]

    def rect(self, element: object) -> Rect:
        key = element if isinstance(element, str) else getattr(element, "name", None)
        if key not in self.rectangles:
            raise KeyError(key)
        return self.rectangles[key]


__all__ = ("Insets", "LayoutResult", "LayoutSpec", "Rect", "RectTransform", "Viewport")
