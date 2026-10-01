"""Immutable, backend-neutral contracts for 2D and future 3D renderers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from numbers import Real
from typing import Protocol, cast, runtime_checkable

from expra_engine.core.math_utils import compose_2d_pose, transform_2d_points
from expra_engine.core.scene.camera import Camera2D
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.runtime.normal_mapping import (
    NormalMapEncoding,
    NormalMapMode,
    NormalYConvention,
    coerce_normal_map_enums,
    validate_normal_strength,
    validate_normal_texture_id,
)
from expra_engine.runtime.validation import finite_float as _finite
from expra_engine.ui_model.geometry import Rect
from expra_engine.ui_model.nine_slice import NineSlice

__all__ = (
    "SUPPORTED_PRIMITIVE_KINDS",
    "Color",
    "LightDescriptor",
    "MaterialDescriptor",
    "NineSliceDescriptor",
    "NormalMapDescriptor",
    "OrthographicCamera",
    "PrimitiveDescriptor",
    "RenderContext",
    "RenderFrame",
    "RenderItem",
    "RenderPhase",
    "RenderSpace",
    "Renderer",
    "RendererCapabilities",
    "TextDescriptor",
    "Transform",
    "Viewport",
    "render_item_order_key",
    "validate_light_bounds",
)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

# Canonical primitive-kind contract shared by extraction and the editor's
# Pygame pixel preflight. The backend must implement every kind in this set.
SUPPORTED_PRIMITIVE_KINDS = frozenset(
    {"point", "rectangle", "rect", "circle", "rounded_rectangle", "polygon", "line"}
)


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
    lighting_2d: bool = False
    normal_mapping_2d: bool = False


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
        x, y, rotation, scale_x, scale_y = compose_2d_pose(
            (self.position[0], self.position[1], self.rotation, self.scale[0], self.scale[1]),
            (child.position[0], child.position[1], child.rotation, child.scale[0], child.scale[1]),
        )
        return Transform(
            position=(x, y, self.position[2] + child.position[2] * self.scale[2]),
            rotation=rotation,
            scale=(scale_x, scale_y, self.scale[2] * child.scale[2]),
        )

    def transform_point(self, point: Vec3) -> Vec3:
        """Map a local point into world coordinates through this transform."""
        return self.transform_points((point,))[0]

    def transform_points(self, points: Iterable[Vec3]) -> tuple[Vec3, ...]:
        """Map a batch of local points through this transform efficiently."""
        local_points = tuple(_tuple(point, 3, "point") for point in points)
        world_points = transform_2d_points(
            (self.position[0], self.position[1], self.rotation, self.scale[0], self.scale[1]),
            ((point[0], point[1]) for point in local_points),
        )
        return tuple(
            (world[0], world[1], self.position[2] + point[2] * self.scale[2])
            for point, world in zip(local_points, world_points, strict=True)
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

    @classmethod
    def from_value(cls, value: Color | Iterable[float]) -> Color:
        """Normalize a three- or four-channel value to an RGBA Color."""
        if isinstance(value, cls):
            return value
        values = tuple(cast(Iterable[float], value))
        if len(values) not in (3, 4):
            raise ValueError("color must contain 3 or 4 values")
        if len(values) == 3:
            return cls(values[0], values[1], values[2])
        return cls(values[0], values[1], values[2], values[3])

    def to_list(self) -> list[float]:
        """Return the canonical RGBA list used by serialized components."""
        return [self.red, self.green, self.blue, self.alpha]


def validate_light_bounds(
    energy: float,
    radius: float,
    falloff: float,
    cone_angle: float,
    height: float,
) -> None:
    """Validate the canonical 2D light parameter ranges.

    Shared by ``LightDescriptor`` (render contract) and ``Light2DComponent``
    (authored component) so the two cannot drift.
    """
    if not 0.0 <= energy <= 8.0:
        raise ValueError("energy must be between 0 and 8")
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    if not 0.1 <= falloff <= 8.0:
        raise ValueError("falloff must be between 0.1 and 8")
    if not 0.0 < cone_angle <= 360.0:
        raise ValueError("cone_angle must be greater than 0 and at most 360")
    if not 0.0 <= height <= 1024.0:
        raise ValueError("height must be between 0 and 1024")


@dataclass(frozen=True)
class LightDescriptor:
    """Backend-neutral world-space data for one dynamic 2D light."""

    entity_id: str
    kind: str
    position: Vec3
    color: Color
    energy: float
    radius: float
    falloff: float
    direction_degrees: float = 0.0
    cone_angle: float = 60.0
    height: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise ValueError("entity_id must not be empty")
        if not isinstance(self.kind, str) or self.kind not in {"point", "spot"}:
            raise ValueError("kind must be 'point' or 'spot'")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in self.position):
            raise ValueError("position must contain finite numeric values")
        object.__setattr__(self, "position", _tuple(self.position, 3, "position"))
        if not isinstance(self.color, Color):
            raise TypeError("color must be a rendering.Color")
        numeric_fields = (
            ("energy", self.energy),
            ("radius", self.radius),
            ("falloff", self.falloff),
            ("direction_degrees", self.direction_degrees),
            ("cone_angle", self.cone_angle),
            ("height", self.height),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, Real) for _, value in numeric_fields
        ):
            invalid = next(
                name
                for name, value in numeric_fields
                if isinstance(value, bool) or not isinstance(value, Real)
            )
            raise ValueError(f"{invalid} must be a finite number")
        energy = _finite(self.energy, "energy")
        radius = _finite(self.radius, "radius")
        falloff = _finite(self.falloff, "falloff")
        direction = _finite(self.direction_degrees, "direction_degrees")
        cone = _finite(self.cone_angle, "cone_angle")
        height = _finite(self.height, "height")
        validate_light_bounds(energy, radius, falloff, cone, height)
        object.__setattr__(self, "energy", energy)
        object.__setattr__(self, "radius", radius)
        object.__setattr__(self, "falloff", falloff)
        object.__setattr__(self, "direction_degrees", direction)
        object.__setattr__(self, "cone_angle", cone)
        object.__setattr__(self, "height", height)

    def is_visible(self, context: RenderContext) -> bool:
        """Conservatively cull lights outside the camera viewport or depth range."""
        if not context.camera.near <= self.position[2] <= context.camera.far:
            return False
        viewport = context.viewport
        center_x, center_y = context.camera.project(self.position[:2], viewport)
        radius_pixels = max(
            self.radius / context.camera.width * viewport.width,
            self.radius / context.camera.height * viewport.height,
        )
        return (
            center_x + radius_pixels >= viewport.x
            and center_x - radius_pixels <= viewport.right
            and center_y + radius_pixels >= viewport.y
            and center_y - radius_pixels <= viewport.bottom
        )


@dataclass(frozen=True)
class NormalMapDescriptor:
    """Backend-neutral normal-map binding and tangent-space interpretation."""

    mode: NormalMapMode | str
    texture_id: str | None = None
    strength: float = 1.0
    y_convention: NormalYConvention | str = NormalYConvention.OPENGL
    encoding: NormalMapEncoding | str = NormalMapEncoding.RGB_XYZ

    def __post_init__(self) -> None:
        mode, convention, encoding = coerce_normal_map_enums(
            self.mode, self.y_convention, self.encoding
        )
        if mode is NormalMapMode.DISABLED:
            raise ValueError("disabled normal mapping must use a None descriptor")
        texture_id = validate_normal_texture_id(self.texture_id)
        if mode is NormalMapMode.EXPLICIT and texture_id is None:
            raise ValueError("explicit normal mapping requires normal_texture_id")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "texture_id", texture_id)
        object.__setattr__(self, "strength", validate_normal_strength(self.strength))
        object.__setattr__(self, "y_convention", convention)
        object.__setattr__(self, "encoding", encoding)


@dataclass(frozen=True)
class MaterialDescriptor:
    color: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))
    opacity: float = 1.0
    texture_id: str | None = None
    tint: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0))
    outline: Color | None = None
    outline_width: float = 0.0
    # Declared forward-compatibility contract, not yet a live behavior. No
    # current backend consumes blend_mode: the reference Pygame renderer
    # advertises ``RendererCapabilities.blend_mode == False`` and draws every
    # material through the same compositing path regardless of this value. The
    # three-value validation stays so a future backend can rely on it, but
    # "add"/"multiply" must not be assumed to change rendering today.
    blend_mode: str = "normal"
    source_region: SpriteRegion | None = None
    light_response: MaterialLightResponse | None = None
    normal_map: NormalMapDescriptor | None = None

    def __post_init__(self) -> None:
        opacity = _finite(self.opacity, "opacity")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError("opacity must be between 0 and 1")
        if self.outline_width < 0.0:
            raise ValueError("outline_width must not be negative")
        _finite(self.outline_width, "outline_width")
        if self.blend_mode not in {"normal", "add", "multiply"}:
            raise ValueError("unsupported blend mode")
        if self.light_response is not None and not isinstance(
            self.light_response, MaterialLightResponse
        ):
            raise TypeError("light_response must be MaterialLightResponse or None")
        if self.normal_map is not None and not isinstance(self.normal_map, NormalMapDescriptor):
            raise TypeError("normal_map must be NormalMapDescriptor or None")


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
    points: tuple[tuple[float, float], ...] = ()
    thickness: float = 1.0

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
        points = tuple(tuple(point) for point in self.points)
        object.__setattr__(self, "points", points)
        if self.kind == "polygon" and len(points) < 3:
            raise ValueError("polygon primitive requires at least three points")
        if self.kind == "line":
            if len(points) != 2:
                raise ValueError("line primitive requires exactly two points")
            thickness = _finite(self.thickness, "thickness")
            object.__setattr__(self, "thickness", thickness)
            if thickness <= 0:
                raise ValueError("line thickness must be positive")


class RenderPhase(IntEnum):
    OPAQUE = 0
    TRANSPARENT = 1
    OVERLAY = 2


class RenderSpace(StrEnum):
    """Coordinate space consumed by a renderer-neutral item."""

    WORLD = "world"
    VIEWPORT = "viewport"


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
    space: RenderSpace = RenderSpace.WORLD
    viewport_anchor: Vec2 | None = None
    viewport_offset: Vec2 = (0.0, 0.0)

    def __post_init__(self) -> None:
        space = self.space if isinstance(self.space, RenderSpace) else RenderSpace(self.space)
        object.__setattr__(self, "space", space)
        if space is RenderSpace.VIEWPORT:
            if self.viewport_anchor is None:
                raise ValueError("viewport-space RenderItem requires a viewport_anchor")
            anchor = _tuple(self.viewport_anchor, 2, "viewport_anchor")
            if any(value < 0.0 or value > 1.0 for value in anchor):
                raise ValueError("viewport_anchor coordinates must be in [0, 1]")
            object.__setattr__(self, "viewport_anchor", (anchor[0], anchor[1]))
            offset = _tuple(self.viewport_offset, 2, "viewport_offset")
            object.__setattr__(self, "viewport_offset", (offset[0], offset[1]))
        elif self.viewport_anchor is not None:
            raise ValueError("world-space RenderItem cannot carry a viewport_anchor")

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

    @property
    def visual_transform(self) -> Transform:
        """Return the transform used to place this item in rendered space."""
        return (
            self.sprite_transform if self.material.texture_id is not None else self.world_transform
        )

    def resolved_transform(self, context: RenderContext) -> Transform:
        """Return a render-only world pose for the current RenderContext.

        World-space items retain their existing transform. Viewport items keep
        pixel-based layout metadata in the frame contract and resolve that
        position/size through the actual camera pose without mutating Scene data.
        """
        transform = self.visual_transform
        if self.space is RenderSpace.WORLD:
            return transform

        assert self.viewport_anchor is not None
        viewport = context.viewport
        anchor_x, anchor_y = self.viewport_anchor
        offset_x, offset_y = self.viewport_offset
        screen_point = (
            viewport.x
            + anchor_x * viewport.width
            + offset_x
            + transform.position[0],
            viewport.y
            + (1.0 - anchor_y) * viewport.height
            - offset_y
            - transform.position[1],
        )
        world_x, world_y = context.camera.unproject(screen_point, viewport)
        return Transform(
            position=(world_x, world_y, transform.position[2]),
            rotation=transform.rotation + math.degrees(context.camera.rotation),
            scale=(
                transform.scale[0] * context.camera.width / viewport.width,
                transform.scale[1] * context.camera.height / viewport.height,
                transform.scale[2],
            ),
        )

    def project_point(
        self,
        context: RenderContext,
        local_point: Vec2 = (0.0, 0.0),
    ) -> tuple[float, float]:
        """Project one visual-local point to pixels without moving scene data."""
        transform = self.visual_transform
        if self.space is RenderSpace.WORLD:
            if local_point == (0.0, 0.0):
                return context.camera.project(transform.position[:2], context.viewport)
            world_point = transform.transform_point((local_point[0], local_point[1], 0.0))
            return context.camera.project(world_point[:2], context.viewport)

        assert self.viewport_anchor is not None
        local_x = local_point[0] * transform.scale[0]
        local_y = local_point[1] * transform.scale[1]
        angle = math.radians(transform.rotation)
        offset_x = local_x * math.cos(angle) - local_y * math.sin(angle)
        offset_y = local_x * math.sin(angle) + local_y * math.cos(angle)
        return (
            context.viewport.x
            + self.viewport_anchor[0] * context.viewport.width
            + self.viewport_offset[0]
            + transform.position[0]
            + offset_x,
            context.viewport.y
            + (1.0 - self.viewport_anchor[1]) * context.viewport.height
            - self.viewport_offset[1]
            - transform.position[1]
            - offset_y,
        )

    def _projected_bounds(
        self,
        context: RenderContext,
        transform: Transform | None = None,
    ) -> tuple[float, float, float, float]:
        transform = transform or self.resolved_transform(context)
        if self.primitive.kind in ("polygon", "line") and self.primitive.points:
            projected = tuple(self.project_point(context, point) for point in self.primitive.points)
            xs = tuple(point[0] for point in projected)
            ys = tuple(point[1] for point in projected)
            if self.primitive.kind == "line":
                padding = (
                    self.primitive.thickness
                    * max(abs(transform.scale[0]), abs(transform.scale[1]))
                    / context.camera.width
                    * context.viewport.width
                    / 2
                )
            else:
                padding = max(self.material.outline_width / 2, 0.5)
            return (
                min(xs) - padding,
                min(ys) - padding,
                max(xs) + padding,
                max(ys) + padding,
            )
        center = self.project_point(context)
        # ``radius`` is overloaded: for circle/point it is the full extent of
        # the shape, but for rounded_rectangle it is only a corner radius --
        # the shape's actual extent is still ``size``. Treating a rounded
        # rectangle's tiny corner radius as its bounding radius would cull it
        # far too aggressively (or too late) during visibility checks.
        radius_is_extent = (
            self.primitive.kind in ("circle", "point") and self.primitive.radius is not None
        )
        screen_rotation = transform.rotation - math.degrees(context.camera.rotation)
        if not radius_is_extent and screen_rotation:
            half_width = abs(self.primitive.size[0] * transform.scale[0]) / 2
            half_height = abs(self.primitive.size[1] * transform.scale[1]) / 2
            corners = (
                (-half_width, -half_height),
                (-half_width, half_height),
                (half_width, -half_height),
                (half_width, half_height),
            )
            projected = tuple(self.project_point(context, point) for point in corners)
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
        transform = self.resolved_transform(context)
        depth = transform.position[2]
        if not context.camera.near <= depth <= context.camera.far:
            return False
        left, top, right, bottom = self._projected_bounds(context, transform)
        return (
            right >= context.viewport.x
            and left <= context.viewport.right
            and bottom >= context.viewport.y
            and top <= context.viewport.bottom
        )


def render_item_order_key(item: RenderItem, insertion_index: int) -> tuple[int, int, float, int]:
    """Return the canonical draw-item sort key shared by the frame and the planner.

    Draw order — phase, then layer, then world depth, then insertion order — is
    a single responsibility. Keeping it here prevents ``RenderFrame.ordered_items``
    and ``RenderOrder.from_item`` from encoding the same rule independently and
    drifting apart.
    """
    return (
        item.phase.value,
        item.layer,
        item.world_transform.position[2],
        insertion_index,
    )


@dataclass(frozen=True)
class RenderFrame:
    items: tuple[RenderItem, ...] = ()
    elapsed: float = 0.0
    payload: object | None = None
    modulation: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0, 1.0))
    submissions: tuple[object, ...] = ()
    lights: tuple[LightDescriptor, ...] = ()
    lighting_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "submissions", tuple(self.submissions))
        object.__setattr__(self, "lights", tuple(self.lights))
        _finite(self.elapsed, "elapsed")
        if not isinstance(self.modulation, Color):
            raise TypeError("modulation must be a Color")
        if any(not isinstance(light, LightDescriptor) for light in self.lights):
            raise TypeError("lights must contain LightDescriptor values")
        if type(self.lighting_enabled) is not bool:
            raise TypeError("lighting_enabled must be a bool")

    def ordered_items(self) -> tuple[RenderItem, ...]:
        return tuple(
            item
            for _, item in sorted(
                enumerate(self.items),
                key=lambda pair: render_item_order_key(pair[1], pair[0]),
            )
        )

    def visible_items(self, context: RenderContext) -> tuple[RenderItem, ...]:
        return tuple(item for item in self.ordered_items() if item.is_visible(context))

    def visible_lights(self, context: RenderContext) -> tuple[LightDescriptor, ...]:
        if not self.lighting_enabled:
            return ()
        return tuple(light for light in self.lights if light.is_visible(context))


@runtime_checkable
class Renderer(Protocol):
    capabilities: RendererCapabilities

    def start(self, context: RenderContext) -> None: ...

    def render(self, frame: RenderFrame) -> None: ...

    def resize(self, viewport: Viewport) -> None: ...

    def stop(self) -> None: ...


# Imported after Color and the backend-neutral contracts are defined: the
# material module depends on Color but not on any renderer implementation.
from expra_engine.runtime.material_lighting import MaterialLightResponse  # noqa: E402
