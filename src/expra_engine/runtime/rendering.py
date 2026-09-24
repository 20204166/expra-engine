"""Immutable, backend-neutral contracts for 2D and future 3D renderers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol, runtime_checkable

from expra_engine.core.scene.camera import Camera2D
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.ui_model.geometry import Rect
from expra_engine.ui_model.nine_slice import NineSlice

__all__ = (
    "Color",
    "MaterialDescriptor",
    "NineSliceDescriptor",
    "OrthographicCamera",
    "PrimitiveDescriptor",
    "RenderContext",
    "RenderFrame",
    "RenderItem",
    "RenderPhase",
    "Renderer",
    "RendererCapabilities",
    "TextDescriptor",
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
    texture: bool = False
    outline: bool = False
    nine_slice: bool = False
    blend_mode: bool = False
    resize: bool = True
    headless: bool = False
    screen_capture: bool = False
    screen_texture: bool = False
    screen_texture_mipmaps: bool = False


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


class OrthographicCamera(Camera2D):
    """Depth-aware runtime camera backed by the shared 2D camera math."""

    def __init__(
        self,
        position: Vec3 = (0.0, 0.0, 0.0),
        width: float = 10.0,
        height: float = 10.0,
        near: float = -1_000.0,
        far: float = 1_000.0,
    ) -> None:
        raw_position = tuple(position)
        if len(raw_position) == 2:
            raw_position = (*raw_position, 0.0)
        x, y, z = _tuple(raw_position, 3, "position")
        width = _finite(width, "width")
        height = _finite(height, "height")
        near = _finite(near, "near")
        far = _finite(far, "far")
        if width <= 0 or height <= 0 or near >= far:
            raise ValueError("camera dimensions must be positive and near must be less than far")

        # The internal viewport anchors the camera dimensions. Runtime
        # projection uses the actual RenderContext viewport.
        super().__init__(position=(x, y), target_width=width, viewport=(width, height))
        self._depth = z
        self.near = near
        self.far = far

    @property
    def position(self) -> Vec3:
        return (*self._position, self._depth)

    @position.setter
    def position(self, value: Vec3 | Vec2) -> None:
        raw_position = tuple(value)
        if len(raw_position) == 2:
            x, y = self._coerce_vec2(raw_position)
            z = self._depth
        else:
            x, y, z = _tuple(raw_position, 3, "position")
        self._position = (x, y)
        self._target_position = (x, y)
        self._depth = z


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
    texture_id: str | None = None
    tint: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))
    outline: Color | None = None
    outline_width: float = 0.0
    blend_mode: str = "normal"
    source_region: SpriteRegion | None = None

    def __post_init__(self) -> None:
        opacity = _finite(self.opacity, "opacity")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError("opacity must be between 0 and 1")
        if self.outline_width < 0.0:
            raise ValueError("outline_width must not be negative")
        _finite(self.outline_width, "outline_width")
        if self.blend_mode not in {"normal", "add", "multiply"}:
            raise ValueError("unsupported blend mode")


@dataclass(frozen=True)
class TextDescriptor:
    """Backend-neutral text data; measurement and rasterization stay injected."""

    text: str = ""
    font: str = "default"
    size: float = 16.0
    color: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))
    max_width: float | None = None
    align: str = "left"

    def __post_init__(self) -> None:
        size = _finite(self.size, "size")
        if size <= 0:
            raise ValueError("text size must be positive")
        if self.max_width is not None and _finite(self.max_width, "max_width") <= 0:
            raise ValueError("max_width must be positive")
        if self.align not in {"left", "center", "right"}:
            raise ValueError("unsupported text alignment")


@dataclass(frozen=True)
class NineSliceDescriptor:
    """A texture and its existing logical nine-slice geometry."""

    texture_id: str
    rect: Rect
    geometry: NineSlice
    tint: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))


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
    payload: object | None = None
    text: TextDescriptor | None = None
    nine_slice: NineSliceDescriptor | None = None
    sprite_offset: Vec2 = (0.0, 0.0)
    sprite_centered: bool = True
    sprite_flip_h: bool = False
    sprite_flip_v: bool = False

    @property
    def world_transform(self) -> Transform:
        return self.parent.compose(self.transform) if self.parent is not None else self.transform

    @property
    def sprite_transform(self) -> Transform:
        """Return the visual transform after sprite-local placement is applied."""
        transform = self.world_transform
        angle = math.radians(transform.rotation)
        offset_x, offset_y = self.sprite_offset
        if not self.sprite_centered:
            offset_x += self.primitive.size[0] / 2
            offset_y += self.primitive.size[1] / 2
        local_x = offset_x * transform.scale[0]
        local_y = offset_y * transform.scale[1]
        return Transform(
            position=(
                transform.position[0] + local_x * math.cos(angle) - local_y * math.sin(angle),
                transform.position[1] + local_x * math.sin(angle) + local_y * math.cos(angle),
                transform.position[2],
            ),
            rotation=transform.rotation,
            scale=transform.scale,
        )

    def _projected_bounds(self, context: RenderContext) -> tuple[float, float, float, float]:
        transform = (
            self.sprite_transform if self.primitive.kind == "sprite" else self.world_transform
        )
        center = context.camera.project(transform.position, context.viewport)
        # ``radius`` is overloaded: for circle/point it is the full extent of
        # the shape, but for rounded_rectangle it is only a corner radius --
        # the shape's actual extent is still ``size``. Treating a rounded
        # rectangle's tiny corner radius as its bounding radius would cull it
        # far too aggressively (or too late) during visibility checks.
        radius_is_extent = self.primitive.kind in ("circle", "point") and self.primitive.radius is not None
        if not radius_is_extent and (transform.rotation or context.camera.rotation):
            half_width = abs(self.primitive.size[0] * transform.scale[0]) / 2
            half_height = abs(self.primitive.size[1] * transform.scale[1]) / 2
            angle = math.radians(transform.rotation)
            cos_angle = math.cos(angle)
            sin_angle = math.sin(angle)
            corners = (
                (-half_width, -half_height),
                (-half_width, half_height),
                (half_width, -half_height),
                (half_width, half_height),
            )
            projected = tuple(
                context.camera.project(
                    (
                        transform.position[0] + local_x * cos_angle - local_y * sin_angle,
                        transform.position[1] + local_x * sin_angle + local_y * cos_angle,
                    ),
                    context.viewport,
                )
                for local_x, local_y in corners
            )
            xs = tuple(point[0] for point in projected)
            ys = tuple(point[1] for point in projected)
            return min(xs), min(ys), max(xs), max(ys)
        if radius_is_extent:
            assert self.primitive.radius is not None
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
    modulation: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0, 1.0))
    submissions: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "submissions", tuple(self.submissions))
        _finite(self.elapsed, "elapsed")
        if not isinstance(self.modulation, Color):
            raise TypeError("modulation must be a Color")

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
