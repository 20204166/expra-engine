"""Immutable, backend-neutral contracts for 2D and future 3D renderers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol, runtime_checkable

__all__ = (
    "Color",
    "MaterialDescriptor",
    "OrthographicCamera",
    "PrimitiveDescriptor",
    "RenderContext",
    "RenderFrame",
    "RenderItem",
    "RenderPhase",
    "Renderer",
    "RendererCapabilities",
    "Transform",
    "Viewport",
)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _tuple(values: tuple[float, ...] | list[float], size: int, name: str) -> tuple[float, ...]:
    if len(values) != size:
        raise ValueError(f"{name} must contain {size} values")
    return tuple(_finite(value, name) for value in values)


@dataclass(frozen=True)
class RendererCapabilities:
    """Features a renderer can consume without exposing backend types."""

    primitive: bool = True
    text: bool = False
    resize: bool = True
    headless: bool = False


@dataclass(frozen=True)
class Viewport:
    """Pixel-space rectangle used by a render context."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.x, self.y, self.width, self.height)):
            raise ValueError("viewport coordinates and dimensions must be integers")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("viewport dimensions must be positive")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, point: tuple[float, float]) -> bool:
        return self.x <= point[0] <= self.right and self.y <= point[1] <= self.bottom


@dataclass(frozen=True)
class OrthographicCamera:
    """A y-up world camera projecting into a y-down pixel viewport."""

    position: Vec3 = (0.0, 0.0, 0.0)
    width: float = 10.0
    height: float = 10.0
    near: float = -1_000.0
    far: float = 1_000.0

    def __post_init__(self) -> None:
        raw_position = tuple(self.position)
        if len(raw_position) == 2:
            raw_position = (*raw_position, 0.0)
        position = _tuple(raw_position, 3, "position")
        object.__setattr__(self, "position", position)
        for name in ("width", "height", "near", "far"):
            _finite(getattr(self, name), name)
        if self.width <= 0 or self.height <= 0 or self.near >= self.far:
            raise ValueError("camera dimensions must be positive and near must be less than far")

    def project(self, point: Vec3 | Vec2, viewport: Viewport) -> tuple[float, float]:
        raw_point = tuple(point)
        values = _tuple(raw_point, 2 if len(raw_point) == 2 else 3, "point")
        x, y = values[:2]
        left = self.position[0] - self.width / 2
        top = self.position[1] + self.height / 2
        return (
            viewport.x + (x - left) / self.width * viewport.width,
            viewport.y + (top - y) / self.height * viewport.height,
        )


@dataclass(frozen=True)
class RenderContext:
    viewport: Viewport
    camera: OrthographicCamera = field(default_factory=OrthographicCamera)


@dataclass(frozen=True)
class Transform:
    """Local position, z rotation, and scale; suitable for parent composition."""

    position: Vec3 = (0.0, 0.0, 0.0)
    rotation: float = 0.0
    scale: Vec3 = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _tuple(self.position, 3, "position"))
        object.__setattr__(self, "scale", _tuple(self.scale, 3, "scale"))
        _finite(self.rotation, "rotation")

    def compose(self, child: Transform) -> Transform:
        angle = math.radians(self.rotation)
        scaled_x = child.position[0] * self.scale[0]
        scaled_y = child.position[1] * self.scale[1]
        x = scaled_x * math.cos(angle) - scaled_y * math.sin(angle)
        y = scaled_x * math.sin(angle) + scaled_y * math.cos(angle)
        return Transform(
            position=(
                self.position[0] + x,
                self.position[1] + y,
                self.position[2] + child.position[2] * self.scale[2],
            ),
            rotation=self.rotation + child.rotation,
            scale=(
                self.scale[0] * child.scale[0],
                self.scale[1] * child.scale[1],
                self.scale[2] * child.scale[2],
            ),
        )


@dataclass(frozen=True)
class Color:
    red: float
    green: float
    blue: float
    alpha: float = 1.0

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue", "alpha"):
            value = _finite(getattr(self, name), name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class MaterialDescriptor:
    color: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))
    opacity: float = 1.0

    def __post_init__(self) -> None:
        opacity = _finite(self.opacity, "opacity")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError("opacity must be between 0 and 1")


@dataclass(frozen=True)
class PrimitiveDescriptor:
    kind: str
    size: Vec2 = (1.0, 1.0)
    radius: float | None = None

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("primitive kind must not be empty")
        size = _tuple(self.size, 2, "size")
        object.__setattr__(self, "size", size)
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError("primitive size must be positive")
        if self.radius is not None:
            radius = _finite(self.radius, "radius")
            if radius <= 0:
                raise ValueError("primitive radius must be positive")


class RenderPhase(IntEnum):
    OPAQUE = 0
    TRANSPARENT = 1
    OVERLAY = 2


@dataclass(frozen=True)
class RenderItem:
    key: str
    primitive: PrimitiveDescriptor
    transform: Transform
    material: MaterialDescriptor = field(default_factory=MaterialDescriptor)
    phase: RenderPhase = RenderPhase.OPAQUE
    layer: int = 0
    parent: Transform | None = None
    visible: bool = True

    @property
    def world_transform(self) -> Transform:
        return self.parent.compose(self.transform) if self.parent is not None else self.transform

    def _projected_bounds(self, context: RenderContext) -> tuple[float, float, float, float]:
        transform = self.world_transform
        center = context.camera.project(transform.position, context.viewport)
        if self.primitive.radius is not None:
            radius = self.primitive.radius * max(abs(transform.scale[0]), abs(transform.scale[1]))
            rx = radius / context.camera.width * context.viewport.width
            ry = radius / context.camera.height * context.viewport.height
        else:
            rx = abs(self.primitive.size[0] * transform.scale[0]) / context.camera.width
            ry = abs(self.primitive.size[1] * transform.scale[1]) / context.camera.height
            rx *= context.viewport.width / 2
            ry *= context.viewport.height / 2
        return (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry)

    def is_visible(self, context: RenderContext) -> bool:
        if not self.visible:
            return False
        depth = self.world_transform.position[2]
        if not context.camera.near <= depth <= context.camera.far:
            return False
        left, top, right, bottom = self._projected_bounds(context)
        return (
            right >= context.viewport.x
            and left <= context.viewport.right
            and bottom >= context.viewport.y
            and top <= context.viewport.bottom
        )


@dataclass(frozen=True)
class RenderFrame:
    items: tuple[RenderItem, ...] = ()
    elapsed: float = 0.0
    payload: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        _finite(self.elapsed, "elapsed")

    def ordered_items(self) -> tuple[RenderItem, ...]:
        return tuple(
            item
            for _, item in sorted(
                enumerate(self.items),
                key=lambda pair: (
                    pair[1].phase.value,
                    pair[1].layer,
                    pair[1].world_transform.position[2],
                    pair[0],
                ),
            )
        )

    def visible_items(self, context: RenderContext) -> tuple[RenderItem, ...]:
        return tuple(item for item in self.ordered_items() if item.is_visible(context))


@runtime_checkable
class Renderer(Protocol):
    capabilities: RendererCapabilities

    def start(self, context: RenderContext) -> None: ...

    def render(self, frame: RenderFrame) -> None: ...

    def resize(self, viewport: Viewport) -> None: ...

    def stop(self) -> None: ...
