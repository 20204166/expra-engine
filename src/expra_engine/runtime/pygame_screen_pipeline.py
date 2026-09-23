"""Pygame executor for Expra's renderer-neutral ordered screen pipeline.

The class in this module is intentionally *not* a renderer. It owns only
backend pixel resources needed by screen capture/mipmap/sampling operations and
delegates ordinary RenderItem drawing back to the canonical PygameRenderer
through a callback.

That split prevents a second sprite/text/primitive renderer from emerging while
still making BackBufferCopy and screen-texture sampling real.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from expra_engine.runtime.render_pipeline import (
    CaptureScreenOp,
    DrawItemOp,
    DrawScreenTextureOp,
    GenerateScreenMipmapsOp,
    RenderPlan,
)
from expra_engine.runtime.rendering import Color, RenderContext, RenderItem, Transform
from expra_engine.runtime.screen_texture import BackBufferCopyMode
from expra_engine.ui_model.geometry import Rect

__all__ = (
    "PygameScreenPipeline",
    "PygameScreenSnapshot",
    "ScreenPipelineError",
    "UnsupportedScreenPipelineFeature",
)


class ScreenPipelineError(RuntimeError):
    pass


class UnsupportedScreenPipelineFeature(ScreenPipelineError):
    pass


@dataclass(frozen=True)
class PygameScreenSnapshot:
    """Backend-owned immutable reference set for one named capture."""

    origin: tuple[int, int]
    levels: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError("snapshot requires at least one surface level")

    @property
    def base(self) -> Any:
        return self.levels[0]

    @property
    def size(self) -> tuple[int, int]:
        getter = getattr(self.base, "get_size", None)
        if not callable(getter):
            raise ScreenPipelineError("captured surface does not expose get_size()")
        width, height = getter()
        return int(width), int(height)


DrawItemCallback = Callable[[RenderItem, Any], None]


class PygameScreenPipeline:
    """Execute capture/mipmap/screen-sampling operations on Pygame-like surfaces."""

    def __init__(self, pygame_module: Any) -> None:
        self.pygame = pygame_module
        self._captures: dict[str, PygameScreenSnapshot] = {}

    @property
    def capture_ids(self) -> tuple[str, ...]:
        return tuple(self._captures)

    def clear(self) -> None:
        self._captures.clear()

    def snapshot(self, capture_id: str = "screen") -> PygameScreenSnapshot | None:
        return self._captures.get(capture_id)

    def execute(
        self,
        plan: RenderPlan,
        *,
        surface: Any,
        context: RenderContext,
        draw_item: DrawItemCallback,
    ) -> None:
        if not isinstance(plan, RenderPlan):
            raise TypeError("plan must be RenderPlan")
        if not isinstance(context, RenderContext):
            raise TypeError("context must be RenderContext")
        if surface is None:
            raise ValueError("surface must not be None")

        for operation in plan.operations:
            if isinstance(operation, DrawItemOp):
                draw_item(operation.item, surface)
            elif isinstance(operation, CaptureScreenOp):
                self._capture(operation, surface, context)
            elif isinstance(operation, GenerateScreenMipmapsOp):
                self._generate_mipmaps(operation.capture_id)
            elif isinstance(operation, DrawScreenTextureOp):
                self._draw_screen_texture(operation, surface, context)
            else:  # pragma: no cover - closed union defensive guard
                raise ScreenPipelineError(
                    f"unsupported render operation: {type(operation).__name__}"
                )

    def _capture(
        self,
        operation: CaptureScreenOp,
        surface: Any,
        context: RenderContext,
    ) -> None:
        request = operation.request
        if request.mode is BackBufferCopyMode.VIEWPORT:
            pixel_rect = Rect(
                context.viewport.x,
                context.viewport.y,
                context.viewport.width,
                context.viewport.height,
            )
        else:
            pixel_rect = self._project_local_rect(
                request.rect,
                request.transform,
                context,
            )

        clipped = self._clip_rect_to_surface(pixel_rect, surface, context)
        if clipped.width <= 0.0 or clipped.height <= 0.0:
            self._captures.pop(request.capture_id, None)
            return

        int_rect = (
            int(math.floor(clipped.x)),
            int(math.floor(clipped.y)),
            max(
                1,
                int(math.ceil(clipped.x + clipped.width))
                - int(math.floor(clipped.x)),
            ),
            max(
                1,
                int(math.ceil(clipped.y + clipped.height))
                - int(math.floor(clipped.y)),
            ),
        )
        subsurface = getattr(surface, "subsurface", None)
        if not callable(subsurface):
            raise UnsupportedScreenPipelineFeature(
                "Pygame surface does not support subsurface capture"
            )
        try:
            captured = subsurface(int_rect)
        except Exception as exc:  # noqa: BLE001 - backend-specific range errors
            raise ScreenPipelineError("screen capture failed") from exc
        copier = getattr(captured, "copy", None)
        if not callable(copier):
            raise UnsupportedScreenPipelineFeature(
                "captured surface does not support copy()"
            )
        self._captures[request.capture_id] = PygameScreenSnapshot(
            (int_rect[0], int_rect[1]),
            (copier(),),
        )

    def _generate_mipmaps(self, capture_id: str) -> None:
        snapshot = self._captures.get(capture_id)
        if snapshot is None:
            raise ScreenPipelineError(
                f"cannot generate mipmaps for missing capture {capture_id!r}"
            )
        transform_api = getattr(self.pygame, "transform", None)
        smoothscale = getattr(transform_api, "smoothscale", None)
        if not callable(smoothscale):
            raise UnsupportedScreenPipelineFeature(
                "Pygame backend cannot generate screen-texture mipmaps"
            )

        levels = [self._ensure_alpha_surface(snapshot.base)]
        width, height = snapshot.size
        while width > 1 or height > 1:
            width = max(1, width // 2)
            height = max(1, height // 2)
            levels.append(smoothscale(levels[-1], (width, height)))
        self._captures[capture_id] = PygameScreenSnapshot(
            snapshot.origin,
            tuple(levels),
        )

    def _draw_screen_texture(
        self,
        operation: DrawScreenTextureOp,
        surface: Any,
        context: RenderContext,
    ) -> None:
        request = operation.request
        snapshot = self._captures.get(request.capture_id)
        if snapshot is None:
            raise ScreenPipelineError(
                f"screen texture {request.capture_id!r} has not been captured"
            )

        level_index = 0
        if request.filter.uses_mipmaps:
            if len(snapshot.levels) == 1:
                width, height = snapshot.size
                if width > 1 or height > 1:
                    raise ScreenPipelineError(
                        f"screen texture {request.capture_id!r} has no mipmaps"
                    )
            level_index = min(
                max(0, int(round(request.lod))),
                len(snapshot.levels) - 1,
            )
        source_surface = snapshot.levels[level_index]
        source_surface = self._crop_uv(source_surface, request.uv_rect)
        source_surface = self._apply_tint_and_opacity(
            source_surface,
            request.tint,
            request.opacity,
        )

        destination = self._project_destination(
            request.transform,
            request.width,
            request.height,
            context,
        )
        target_size = (
            max(1, int(round(destination.width))),
            max(1, int(round(destination.height))),
        )
        source_surface = self._scale(
            source_surface,
            target_size,
            linear=request.filter.linear,
        )

        angle = request.transform.rotation - math.degrees(context.camera.rotation)
        transform_api = getattr(self.pygame, "transform", None)
        rotate = getattr(transform_api, "rotate", None)
        if angle:
            if not callable(rotate):
                raise UnsupportedScreenPipelineFeature(
                    "Pygame backend cannot rotate screen-texture draws"
                )
            source_surface = self._ensure_alpha_surface(source_surface)
            source_surface = rotate(source_surface, angle)

        get_rect = getattr(source_surface, "get_rect", None)
        center = (
            round(destination.x + destination.width / 2.0),
            round(destination.y + destination.height / 2.0),
        )
        destination_rect = (
            get_rect(center=center)
            if callable(get_rect)
            else (
                round(destination.x),
                round(destination.y),
                target_size[0],
                target_size[1],
            )
        )
        blit = getattr(surface, "blit", None)
        if not callable(blit):
            raise UnsupportedScreenPipelineFeature(
                "Pygame target surface does not support blit()"
            )
        blit(source_surface, destination_rect)

    def _crop_uv(self, surface: Any, uv: Rect) -> Any:
        if uv == Rect(0.0, 0.0, 1.0, 1.0):
            copier = getattr(surface, "copy", None)
            return copier() if callable(copier) else surface

        getter = getattr(surface, "get_size", None)
        subsurface = getattr(surface, "subsurface", None)
        if not callable(getter) or not callable(subsurface):
            raise UnsupportedScreenPipelineFeature(
                "Pygame surface cannot crop normalized screen-texture UVs"
            )
        width, height = getter()
        left = int(math.floor(uv.x * width))
        top = int(math.floor(uv.y * height))
        right = int(math.ceil((uv.x + uv.width) * width))
        bottom = int(math.ceil((uv.y + uv.height) * height))
        right = min(int(width), max(left + 1, right))
        bottom = min(int(height), max(top + 1, bottom))
        cropped = subsurface((left, top, right - left, bottom - top))
        copier = getattr(cropped, "copy", None)
        return copier() if callable(copier) else cropped

    def _apply_tint_and_opacity(
        self,
        surface: Any,
        tint: Color,
        opacity: float,
    ) -> Any:
        neutral = tint == Color(1.0, 1.0, 1.0, 1.0) and opacity >= 1.0
        copier = getattr(surface, "copy", None)
        if not callable(copier) and not neutral:
            raise UnsupportedScreenPipelineFeature(
                "Pygame surface cannot be copied before tinting"
            )
        if neutral:
            return copier() if callable(copier) else surface

        result = self._copy_with_alpha(surface)

        blend = getattr(self.pygame, "BLEND_RGBA_MULT", None)
        fill = getattr(result, "fill", None)
        if blend is None or not callable(fill):
            raise UnsupportedScreenPipelineFeature(
                "Pygame backend cannot tint screen textures without mutation"
            )
        rgba = (
            round(tint.red * 255),
            round(tint.green * 255),
            round(tint.blue * 255),
            round(tint.alpha * opacity * 255),
        )
        fill(rgba, special_flags=blend)
        return result

    def _copy_with_alpha(self, surface: Any) -> Any:
        copier = getattr(surface, "copy", None)
        if not callable(copier):
            raise UnsupportedScreenPipelineFeature(
                "Pygame surface cannot be copied before tinting"
            )
        return self._ensure_alpha_surface(copier())

    def _ensure_alpha_surface(self, surface: Any) -> Any:
        has_alpha = self._has_per_pixel_alpha(surface)
        if has_alpha is not False:
            return surface

        getter = getattr(surface, "get_size", None)
        if not callable(getter):
            raise UnsupportedScreenPipelineFeature(
                "Pygame surface does not expose get_size() for alpha conversion"
            )
        width, height = getter()
        source_alpha = getattr(self.pygame, "SRCALPHA", None)
        surface_factory = getattr(self.pygame, "Surface", None)
        if callable(surface_factory) and source_alpha is not None:
            try:
                converted = surface_factory((int(width), int(height)), flags=source_alpha)
            except TypeError:
                converted = surface_factory((int(width), int(height)), source_alpha)
            blit = getattr(converted, "blit", None)
            if not callable(blit):
                raise UnsupportedScreenPipelineFeature(
                    "Pygame alpha surface does not support blit()"
                )
            blit(surface, (0, 0))
            return converted

        convert_alpha = getattr(surface, "convert_alpha", None)
        if callable(convert_alpha):
            return convert_alpha()
        raise UnsupportedScreenPipelineFeature(
            "Pygame backend cannot create an alpha-capable screen texture"
        )

    def _has_per_pixel_alpha(self, surface: Any) -> bool | None:
        getter = getattr(surface, "get_flags", None)
        source_alpha = getattr(self.pygame, "SRCALPHA", None)
        if not callable(getter) or source_alpha is None:
            return None
        try:
            return bool(int(getter()) & int(source_alpha))
        except (TypeError, ValueError):
            return None

    def _scale(
        self,
        surface: Any,
        size: tuple[int, int],
        *,
        linear: bool,
    ) -> Any:
        transform_api = getattr(self.pygame, "transform", None)
        method = (
            getattr(transform_api, "smoothscale", None)
            if linear
            else getattr(transform_api, "scale", None)
        )
        if not callable(method):
            raise UnsupportedScreenPipelineFeature(
                "Pygame backend cannot scale screen textures"
            )
        if linear:
            surface = self._ensure_alpha_surface(surface)
        return method(surface, size)

    @staticmethod
    def _world_point(
        local: tuple[float, float],
        transform: Transform,
    ) -> tuple[float, float]:
        x = local[0] * transform.scale[0]
        y = local[1] * transform.scale[1]
        angle = math.radians(transform.rotation)
        return (
            transform.position[0] + x * math.cos(angle) - y * math.sin(angle),
            transform.position[1] + x * math.sin(angle) + y * math.cos(angle),
        )

    @classmethod
    def _project_local_rect(
        cls,
        rect: Rect,
        transform: Transform,
        context: RenderContext,
    ) -> Rect:
        corners = (
            (rect.x, rect.y),
            (rect.x + rect.width, rect.y),
            (rect.x + rect.width, rect.y + rect.height),
            (rect.x, rect.y + rect.height),
        )
        projected = tuple(
            context.camera.project(cls._world_point(point, transform), context.viewport)
            for point in corners
        )
        xs = tuple(point[0] for point in projected)
        ys = tuple(point[1] for point in projected)
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @staticmethod
    def _project_destination(
        transform: Transform,
        width: float,
        height: float,
        context: RenderContext,
    ) -> Rect:
        center = context.camera.project(transform.position, context.viewport)
        pixel_width = (
            abs(width * transform.scale[0])
            / context.camera.width
            * context.viewport.width
        )
        pixel_height = (
            abs(height * transform.scale[1])
            / context.camera.height
            * context.viewport.height
        )
        return Rect(
            center[0] - pixel_width / 2.0,
            center[1] - pixel_height / 2.0,
            pixel_width,
            pixel_height,
        )

    @staticmethod
    def _clip_rect_to_surface(
        rect: Rect,
        surface: Any,
        context: RenderContext,
    ) -> Rect:
        getter = getattr(surface, "get_size", None)
        if not callable(getter):
            raise UnsupportedScreenPipelineFeature(
                "Pygame target surface does not expose get_size()"
            )
        surface_width, surface_height = getter()
        left = max(float(context.viewport.x), rect.x, 0.0)
        top = max(float(context.viewport.y), rect.y, 0.0)
        right = min(
            float(context.viewport.right),
            rect.x + rect.width,
            float(surface_width),
        )
        bottom = min(
            float(context.viewport.bottom),
            rect.y + rect.height,
            float(surface_height),
        )
        return Rect(
            left,
            top,
            max(0.0, right - left),
            max(0.0, bottom - top),
        )
