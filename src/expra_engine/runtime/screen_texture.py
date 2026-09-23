"""Renderer-neutral screen-texture and back-buffer scene contracts.

This module preserves the useful 2D screen-texture ideas from Godot's
BackBufferCopy/canvas renderer without importing RenderingServer, RID,
RenderingDevice, shader compiler, Pygame, or a second scene/render system.

The important behavior retained is:

* explicit back-buffer capture at a deterministic canvas position;
* full-viewport or transformed local-rectangle capture;
* named capture slots so multiple effects can coexist;
* a real screen-texture consumer component;
* nearest/linear and mipmapped sampling intent;
* usage metadata that lets the render planner request a capture/mipmaps lazily;
* serializable component data only -- backend surfaces remain runtime-owned.

The render planner and backend executor live in separate modules so scene data,
render ordering, and backend pixel ownership stay distinct.

Concepts adapted from the Godot Engine renderer (MIT licensed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.rendering import Color, RenderPhase, Transform
from expra_engine.ui_model.geometry import Rect

__all__ = (
    "BackBufferCopyComponent",
    "BackBufferCopyMode",
    "BackBufferCopyRequest",
    "RenderEffect",
    "ScreenTextureComponent",
    "ScreenTextureDrawRequest",
    "ScreenTextureFilter",
    "ScreenTextureUsage",
    "render_phase_from_value",
)


_WHITE = Color(1.0, 1.0, 1.0, 1.0)


class BackBufferCopyMode(str, Enum):
    DISABLED = "disabled"
    RECT = "rect"
    VIEWPORT = "viewport"


class ScreenTextureFilter(str, Enum):
    NEAREST = "nearest"
    LINEAR = "linear"
    NEAREST_MIPMAP = "nearest_mipmap"
    LINEAR_MIPMAP = "linear_mipmap"

    @property
    def uses_mipmaps(self) -> bool:
        return self in {
            ScreenTextureFilter.NEAREST_MIPMAP,
            ScreenTextureFilter.LINEAR_MIPMAP,
        }

    @property
    def linear(self) -> bool:
        return self in {
            ScreenTextureFilter.LINEAR,
            ScreenTextureFilter.LINEAR_MIPMAP,
        }


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _non_negative(value: object, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _capture_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("capture_id must be a string")
    result = value.strip()
    if not result:
        raise ValueError("capture_id must not be empty")
    return result


def _rect(value: Rect | tuple[float, float, float, float] | list[float], name: str) -> Rect:
    if isinstance(value, Rect):
        return value
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain x, y, width, height")
    values = tuple(value)
    if len(values) != 4:
        raise ValueError(f"{name} must contain x, y, width, height")
    return Rect(*(float(item) for item in values))


def _color(value: Color | tuple[float, ...] | list[float]) -> Color:
    if isinstance(value, Color):
        return value
    values = tuple(value)
    if len(values) not in (3, 4):
        raise ValueError("color must contain 3 or 4 values")
    return Color(*values)


def _color_dict(value: Color) -> list[float]:
    return [value.red, value.green, value.blue, value.alpha]


def render_phase_from_value(value: RenderPhase | str | int) -> RenderPhase:
    if isinstance(value, RenderPhase):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        by_name = {
            "opaque": RenderPhase.OPAQUE,
            "transparent": RenderPhase.TRANSPARENT,
            "overlay": RenderPhase.OVERLAY,
        }
        if normalized in by_name:
            return by_name[normalized]
        raise ValueError(f"unsupported render phase: {value!r}")
    try:
        return RenderPhase(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported render phase: {value!r}") from exc


def _phase_name(value: RenderPhase) -> str:
    return value.name.lower()


def _uv_rect(
    value: Rect | tuple[float, float, float, float] | list[float],
) -> Rect:
    rect = _rect(value, "uv_rect")
    if (
        rect.x < 0.0
        or rect.y < 0.0
        or rect.x + rect.width > 1.0
        or rect.y + rect.height > 1.0
    ):
        raise ValueError("uv_rect must remain inside normalized [0, 1] coordinates")
    return rect


class BackBufferCopyComponent(Component):
    """Serializable request to snapshot already-rendered pixels.

    ``RECT`` uses ``rect`` in the owning entity's local coordinates. The render
    backend transforms that rectangle through the entity's world transform and
    camera, then clips the resulting pixel bounds to the active viewport.

    ``VIEWPORT`` ignores the local rectangle and snapshots the current viewport.
    ``DISABLED`` remains serializable but emits no runtime capture operation.

    ``capture_id`` names the runtime screen-texture slot. The default ``screen``
    mirrors the single shared screen texture used by ordinary screen effects,
    while named slots permit independent effects without backend-specific state.
    """

    component_type = "back_buffer_copy"

    def __init__(
        self,
        *,
        copy_mode: BackBufferCopyMode | str = BackBufferCopyMode.RECT,
        rect: Rect | tuple[float, float, float, float] | list[float] = (
            -100.0,
            -100.0,
            200.0,
            200.0,
        ),
        capture_id: str = "screen",
        layer: int = 0,
        phase: RenderPhase | str | int = RenderPhase.OPAQUE,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=_boolean(enabled, "enabled"))
        self.copy_mode = (
            copy_mode
            if isinstance(copy_mode, BackBufferCopyMode)
            else BackBufferCopyMode(str(copy_mode))
        )
        self.rect = _rect(rect, "rect")
        self.capture_id = _capture_id(capture_id)
        self.layer = int(layer)
        self.phase = render_phase_from_value(phase)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "copy_mode": self.copy_mode.value,
            "rect": [self.rect.x, self.rect.y, self.rect.width, self.rect.height],
            "capture_id": self.capture_id,
            "layer": self.layer,
            "phase": _phase_name(self.phase),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackBufferCopyComponent":
        return cls(
            copy_mode=str(data.get("copy_mode", BackBufferCopyMode.RECT.value)),
            rect=tuple(data.get("rect", (-100.0, -100.0, 200.0, 200.0))),  # type: ignore[arg-type]
            capture_id=data.get("capture_id", "screen"),
            layer=int(data.get("layer", 0)),
            phase=data.get("phase", "opaque"),
            enabled=_boolean(data.get("enabled", True), "enabled"),
        )


class ScreenTextureComponent(Component):
    """Draw from a previously captured screen texture.

    This is Expra's renderer-neutral replacement for needing a full shader
    language merely to prove screen-texture consumption is real. It is useful
    on its own for mirrors, magnifiers, pixelated/blurred snapshots, portals,
    frozen regions, feedback-style UI and later shader/post-process inputs.

    ``uv_rect`` is normalized inside the selected capture. Destination
    ``width``/``height`` are world-space dimensions centered on the owning
    entity transform. ``lod`` selects the desired mip level when a mipmapped
    filter is requested.
    """

    component_type = "screen_texture"

    def __init__(
        self,
        *,
        capture_id: str = "screen",
        uv_rect: Rect | tuple[float, float, float, float] | list[float] = (
            0.0,
            0.0,
            1.0,
            1.0,
        ),
        width: float = 1.0,
        height: float = 1.0,
        filter: ScreenTextureFilter | str = ScreenTextureFilter.LINEAR,
        lod: float = 0.0,
        tint: Color | tuple[float, ...] | list[float] = _WHITE,
        opacity: float = 1.0,
        layer: int = 0,
        phase: RenderPhase | str | int = RenderPhase.TRANSPARENT,
        visible: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=_boolean(enabled, "enabled"))
        self.capture_id = _capture_id(capture_id)
        self.uv_rect = _uv_rect(uv_rect)
        self.width = _positive(width, "width")
        self.height = _positive(height, "height")
        self.filter = (
            filter
            if isinstance(filter, ScreenTextureFilter)
            else ScreenTextureFilter(str(filter))
        )
        self.lod = _non_negative(lod, "lod")
        self.tint = _color(tint)
        self.opacity = _non_negative(opacity, "opacity")
        if self.opacity > 1.0:
            raise ValueError("opacity must be in [0, 1]")
        self.layer = int(layer)
        self.phase = render_phase_from_value(phase)
        self.visible = _boolean(visible, "visible")

    @property
    def usage(self) -> "ScreenTextureUsage":
        return ScreenTextureUsage(
            capture_id=self.capture_id,
            uses_screen_texture=True,
            uses_mipmaps=self.filter.uses_mipmaps,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "capture_id": self.capture_id,
            "uv_rect": [
                self.uv_rect.x,
                self.uv_rect.y,
                self.uv_rect.width,
                self.uv_rect.height,
            ],
            "width": self.width,
            "height": self.height,
            "filter": self.filter.value,
            "lod": self.lod,
            "tint": _color_dict(self.tint),
            "opacity": self.opacity,
            "layer": self.layer,
            "phase": _phase_name(self.phase),
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreenTextureComponent":
        return cls(
            capture_id=data.get("capture_id", "screen"),
            uv_rect=tuple(data.get("uv_rect", (0.0, 0.0, 1.0, 1.0))),  # type: ignore[arg-type]
            width=data.get("width", 1.0),
            height=data.get("height", 1.0),
            filter=str(data.get("filter", ScreenTextureFilter.LINEAR.value)),
            lod=data.get("lod", 0.0),
            tint=data.get("tint", (1.0, 1.0, 1.0, 1.0)),
            opacity=data.get("opacity", 1.0),
            layer=int(data.get("layer", 0)),
            phase=data.get("phase", "transparent"),
            visible=_boolean(data.get("visible", True), "visible"),
            enabled=_boolean(data.get("enabled", True), "enabled"),
        )


@dataclass(frozen=True)
class ScreenTextureUsage:
    """Resource-usage metadata analogous to shader compiler usage flags."""

    capture_id: str = "screen"
    uses_screen_texture: bool = False
    uses_mipmaps: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_id", _capture_id(self.capture_id))
        if self.uses_mipmaps and not self.uses_screen_texture:
            raise ValueError("mipmaps require screen-texture usage")


@dataclass(frozen=True)
class BackBufferCopyRequest:
    """Renderer-neutral capture request before pixel-space resolution."""

    entity_id: str
    capture_id: str
    mode: BackBufferCopyMode
    transform: Transform = field(default_factory=Transform)
    rect: Rect = field(default_factory=lambda: Rect(-100.0, -100.0, 200.0, 200.0))

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("entity_id must not be empty")
        object.__setattr__(self, "capture_id", _capture_id(self.capture_id))
        if not isinstance(self.mode, BackBufferCopyMode):
            try:
                object.__setattr__(self, "mode", BackBufferCopyMode(str(self.mode)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported copy mode: {self.mode!r}") from exc
        if self.mode is BackBufferCopyMode.DISABLED:
            raise ValueError("disabled mode does not produce a capture request")
        if not isinstance(self.transform, Transform):
            raise TypeError("transform must be rendering.Transform")
        if not isinstance(self.rect, Rect):
            raise TypeError("rect must be ui_model.geometry.Rect")


@dataclass(frozen=True)
class ScreenTextureDrawRequest:
    """Renderer-neutral draw request consuming a captured screen texture."""

    entity_id: str
    capture_id: str
    transform: Transform
    width: float
    height: float
    uv_rect: Rect = field(default_factory=lambda: Rect(0.0, 0.0, 1.0, 1.0))
    filter: ScreenTextureFilter = ScreenTextureFilter.LINEAR
    lod: float = 0.0
    tint: Color = _WHITE
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("entity_id must not be empty")
        object.__setattr__(self, "capture_id", _capture_id(self.capture_id))
        if not isinstance(self.transform, Transform):
            raise TypeError("transform must be rendering.Transform")
        object.__setattr__(self, "width", _positive(self.width, "width"))
        object.__setattr__(self, "height", _positive(self.height, "height"))
        object.__setattr__(self, "uv_rect", _uv_rect(self.uv_rect))
        if not isinstance(self.filter, ScreenTextureFilter):
            object.__setattr__(self, "filter", ScreenTextureFilter(str(self.filter)))
        object.__setattr__(self, "lod", _non_negative(self.lod, "lod"))
        if not isinstance(self.tint, Color):
            raise TypeError("tint must be rendering.Color")
        opacity = _non_negative(self.opacity, "opacity")
        if opacity > 1.0:
            raise ValueError("opacity must be in [0, 1]")
        object.__setattr__(self, "opacity", opacity)

    @property
    def usage(self) -> ScreenTextureUsage:
        return ScreenTextureUsage(
            self.capture_id,
            uses_screen_texture=True,
            uses_mipmaps=self.filter.uses_mipmaps,
        )


@dataclass(frozen=True)
class RenderEffect:
    request: BackBufferCopyRequest | ScreenTextureDrawRequest
    phase: RenderPhase
    layer: int


from expra_engine.core.component import _register_screen_components

_register_screen_components()
