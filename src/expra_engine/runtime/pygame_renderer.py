"""Primitive Pygame renderer kept separate from the renderer-neutral engine."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import Any, cast

from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.canvas_effects import modulate_color
from expra_engine.runtime.pygame_geometry import draw_rounded_rectangle, projected_rectangle_points
from expra_engine.runtime.pygame_renderer_legacy import (
    LegacyPygameRenderMixin,
    RenderFrame,
)
from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
from expra_engine.runtime.pygame_screen_pipeline import PygameScreenPipeline
from expra_engine.runtime.render_diagnostics import FailureKey, RenderDiagnostics
from expra_engine.runtime.render_pipeline import RenderPlanBuilder
from expra_engine.runtime.rendering import (
    Color,
    NineSliceDescriptor,
    RenderContext,
    RendererCapabilities,
    RenderItem,
    TextDescriptor,
)
from expra_engine.runtime.rendering import RenderFrame as ContractRenderFrame
from expra_engine.ui_model.geometry import Insets, Rect

__all__ = ("PygameRenderFrame", "PygameRenderer", "PygameResourceProvider", "RenderFrame")

_LOGGER = logging.getLogger(__name__)


class PygameRenderer(LegacyPygameRenderMixin):
    """Draw tagged scene entities as simple 2D primitives.

    Pygame is supplied by the caller so this class can be tested with a fake
    drawing surface and never needs to create a display itself.
    """

    def __init__(
        self,
        pygame_module: Any,
        surface: Any | None,
        *,
        screen_size: tuple[int, int] = (800, 600),
        world_bounds: tuple[float, float, float, float] = (0, 0, 100, 100),
        arena_bounds: tuple[int, int, int, int] | None = None,
        font_size: int = 24,
        font_provider: Any | None = None,
        resource_provider: Any | None = None,
        clear_color: tuple[int, ...] | None = (10, 14, 30),
        diagnostics: RenderDiagnostics | None = None,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        self.pygame = pygame_module
        self.surface = surface
        self.screen_size = screen_size
        self.world_bounds = world_bounds
        self.arena_bounds = arena_bounds if arena_bounds is not None else (0, 0, *screen_size)
        self._validate_bounds(self.world_bounds, "world_bounds")
        self._validate_bounds(self.arena_bounds, "arena_bounds")
        self._font_provider = font_provider or self._default_font_provider
        self._resource_provider = resource_provider
        self._clear_color = clear_color
        self._draw_failed = False
        self._backend_failure_detail: str | None = None
        self._observer = observer
        self._diagnostics = diagnostics if diagnostics is not None else RenderDiagnostics(_LOGGER)
        self._screen_pipeline = PygameScreenPipeline(pygame_module)
        try:
            self.font = self._font_provider(None, font_size)
        except Exception:  # noqa: BLE001 - backend/font failures must not abort a frame
            self.font = None
        self._engine: Any = None
        self.context: RenderContext | None = None
        self.capabilities = RendererCapabilities(
            primitive=True,
            text=True,
            texture=resource_provider is not None,
            outline=True,
            nine_slice=resource_provider is not None,
            blend_mode=False,
            resize=True,
            headless=True,
            screen_capture=False,
            screen_texture=False,
            screen_texture_mipmaps=False,
        )
        self._update_screen_capabilities()

    def start(self, context: RenderContext) -> None:
        self._screen_pipeline.clear()
        self.context = context
        self._draw_failed = False

    @property
    def draw_failed(self) -> bool:
        """Whether an item failed after a frame began drawing."""
        return self._draw_failed

    def resize(self, viewport: Any) -> None:
        self._screen_pipeline.clear()
        self._diagnostics.clear()
        self.context = (
            RenderContext(viewport, self.context.camera)
            if self.context
            else RenderContext(viewport)
        )
        self.screen_size = (viewport.width, viewport.height)
        self.arena_bounds = (
            self.arena_bounds[0],
            self.arena_bounds[1],
            viewport.width,
            viewport.height,
        )

    def set_surface(self, surface: Any) -> None:
        self.surface = surface
        self._screen_pipeline.clear()
        self._diagnostics.clear()
        self._update_screen_capabilities()

    def stop(self) -> None:
        self._screen_pipeline.clear()
        self._diagnostics.clear()
        self._engine = None
        self.context = None

    def _update_screen_capabilities(self) -> None:
        surface = self.surface
        transform = getattr(self.pygame, "transform", None)
        can_capture = surface is not None and all(
            callable(getattr(surface, name, None)) for name in ("subsurface", "copy", "get_size")
        )
        can_scale = callable(getattr(transform, "scale", None))
        can_linear_scale = callable(getattr(transform, "smoothscale", None))
        can_sample = (
            can_capture
            and callable(getattr(surface, "blit", None))
            and can_scale
            and can_linear_scale
        )
        self.capabilities = replace(
            self.capabilities,
            screen_capture=can_capture,
            screen_texture=can_sample,
            screen_texture_mipmaps=can_sample,
        )

    def _clear_surface(self, surface: Any, draw: Any) -> bool:
        try:
            if self._clear_color is None:
                fill = getattr(surface, "fill", None)
                if not callable(fill):
                    return False
                fill((0, 0, 0, 0))
                return True
            rect = getattr(draw, "rect", None)
            if not callable(rect):
                return False
            rect(surface, self._clear_color, self._rect(self.arena_bounds))
            return True
        except Exception:  # noqa: BLE001 - backend clear failures require fallback
            return False

    def _fail_frame(self, key: FailureKey, message: str) -> None:
        self._draw_failed = True
        self._backend_failure_detail = str(key[-1]) if key else "unknown"
        self._diagnostics.report(key, message)

    def render(self, frame: ContractRenderFrame) -> None:
        """Render a backend-neutral frame of primitive descriptors."""
        self._screen_pipeline.clear()
        self._draw_failed = False
        self._backend_failure_detail = None
        observer = self._observer
        token = observer.begin("render:backend") if observer is not None else None
        try:
            self._render_frame(frame)
        finally:
            if observer is not None and token is not None:
                observer.finish(
                    token,
                    outcome="failure" if self._draw_failed else "success",
                    detail=self._backend_failure_detail or "draw_item_failed" if self._draw_failed else None,
                )

    def _render_frame(self, frame: ContractRenderFrame) -> None:
        context = self.context
        if context is None:
            self._fail_frame(
                ("renderer", "lifecycle", "no-context"),
                "[Render] renderer has no active context",
            )
            return
        draw = getattr(self.pygame, "draw", None)
        surface = self.surface
        if draw is None:
            self._fail_frame(
                ("renderer", "backend", "draw-module"),
                "[Render] Pygame draw capability unavailable",
            )
            return
        if surface is None:
            self._fail_frame(
                ("renderer", "backend", "surface"),
                "[Render] renderer has no target surface",
            )
            return
        if not self._clear_surface(surface, draw):
            self._fail_frame(
                ("renderer", "backend", "clear"),
                "[Render] renderer could not clear target surface",
            )
            return
        if frame.submissions:
            self._screen_pipeline.execute(
                RenderPlanBuilder.from_frame(frame, context),
                surface=surface,
                context=context,
                draw_item=lambda item, target: self._draw_contract_item(
                    item, target, frame.modulation, context
                ),
            )
        else:
            for item in frame.visible_items(context):
                self._draw_contract_item(item, surface, frame.modulation, context)
        if isinstance(frame.payload, RenderFrame):
            self.on_render(frame.payload, clear=False)
        if not self._draw_failed:
            self._diagnostics.clear()
            reset_diagnostics = getattr(self._resource_provider, "reset_diagnostics", None)
            if callable(reset_diagnostics):
                reset_diagnostics()

    def _draw_contract_item(
        self,
        item: RenderItem,
        surface: Any,
        modulation: Color,
        context: RenderContext,
    ) -> None:
        transform = item.visual_transform
        center = context.camera.project(
            (transform.position[0], transform.position[1]), context.viewport
        )
        position = (round(center[0]), round(center[1]))
        color = self._color(
            modulate_color(
                self._tint(item.material.color, item.material.tint),
                modulation,
            ),
            item.material.opacity,
        )
        draw = getattr(self.pygame, "draw", None)
        if draw is None:
            return
        try:
            if item.material.texture_id is not None:
                if self._resource_provider is None:
                    self._draw_failed = True
                    self._diagnostics.report(
                        ("renderer", "texture", item.material.texture_id, "no-provider"),
                        "[Texture] No resource provider attached to renderer for %s",
                        item.material.texture_id,
                    )
                    return
                texture = self._resource_provider(item.material.texture_id)
                if texture is None:
                    self._draw_failed = True
                    self._diagnostics.report(
                        ("renderer", "texture", item.material.texture_id, "unavailable"),
                        "[Texture] Renderer received no texture for %s",
                        item.material.texture_id,
                    )
                    return
                source_region = item.material.source_region
                if source_region is not None:
                    subsurface = getattr(texture, "subsurface", None)
                    if callable(subsurface):
                        texture = subsurface(
                            (
                                source_region.x,
                                source_region.y,
                                source_region.width,
                                source_region.height,
                            )
                        )
                width = round(
                    abs(
                        item.primitive.size[0]
                        * transform.scale[0]
                        / context.camera.width
                        * context.viewport.width
                    )
                )
                height = round(
                    abs(
                        item.primitive.size[1]
                        * transform.scale[1]
                        / context.camera.height
                        * context.viewport.height
                    )
                )
                angle = transform.rotation - math.degrees(context.camera.rotation)
                texture = self._prepare_texture_for_transform(texture, require_alpha=bool(angle))
                rendered_texture = (
                    texture
                    if modulation == Color(1.0, 1.0, 1.0, 1.0)
                    else self._tinted_texture(
                        texture,
                        modulate_color(item.material.tint, modulation),
                    )
                )
                if rendered_texture is None:
                    self._draw_failed = True
                    self._diagnostics.report(
                        ("renderer", "texture", item.material.texture_id, "tint"),
                        "[Texture] Renderer could not prepare %s",
                        item.material.texture_id,
                    )
                    return
                transform_api = getattr(self.pygame, "transform", None)
                if transform_api is not None and (item.sprite_flip_h or item.sprite_flip_v):
                    flip = getattr(transform_api, "flip", None)
                    if callable(flip):
                        rendered_texture = flip(
                            rendered_texture, item.sprite_flip_h, item.sprite_flip_v
                        )
                if transform_api is not None and hasattr(transform_api, "smoothscale"):
                    rendered_texture = transform_api.smoothscale(rendered_texture, (width, height))
                if angle and transform_api is not None:
                    rendered_texture = transform_api.rotate(rendered_texture, angle)
                get_size = cast(
                    Callable[[], tuple[int, int]] | None,
                    getattr(rendered_texture, "get_size", None),
                )
                texture_size = get_size() if callable(get_size) else (width, height)
                draw_position = position
                destination = self._rect_from_center(
                    draw_position, round(texture_size[0]), round(texture_size[1])
                )
                surface.blit(rendered_texture, destination)
                return
            if item.text is not None:
                self._draw_text_to_surface(
                    TextDescriptor(
                        item.text.text,
                        item.text.font,
                        item.text.size,
                        modulate_color(item.text.color, modulation),
                        item.text.max_width,
                        item.text.align,
                    ),
                    position,
                    item.material.opacity,
                    surface,
                )
                return
            if item.nine_slice is not None:
                self._draw_nine_slice_to_surface(
                    item.nine_slice,
                    modulate_color(item.material.tint, modulation),
                    apply_tint=modulation != Color(1.0, 1.0, 1.0, 1.0),
                    surface=surface,
                )
                return
            if item.primitive.kind in ("rectangle", "rect"):
                if transform.rotation or context.camera.rotation:
                    polygon = getattr(draw, "polygon", None)
                    if not callable(polygon):
                        raise RuntimeError("Pygame backend cannot draw transformed rectangles")
                    points = projected_rectangle_points(item, transform, context)
                    polygon(surface, color, points)
                    if item.material.outline is not None and item.material.outline_width:
                        polygon(
                            surface,
                            self._color(
                                modulate_color(item.material.outline, modulation),
                                item.material.opacity,
                            ),
                            points,
                            round(item.material.outline_width),
                        )
                else:
                    width = round(
                        abs(
                            item.primitive.size[0]
                            * transform.scale[0]
                            / context.camera.width
                            * context.viewport.width
                        )
                    )
                    height = round(
                        abs(
                            item.primitive.size[1]
                            * transform.scale[1]
                            / context.camera.height
                            * context.viewport.height
                        )
                    )
                    rectangle = self._rect_from_center(position, width, height)
                    draw.rect(surface, color, rectangle)
                    if item.material.outline is not None and item.material.outline_width:
                        draw.rect(
                            surface,
                            self._color(
                                modulate_color(item.material.outline, modulation),
                                item.material.opacity,
                            ),
                            rectangle,
                            round(item.material.outline_width),
                        )
            elif item.primitive.kind == "rounded_rectangle":
                draw_rounded_rectangle(
                    self, surface, draw, item, transform, context, position, color, modulation
                )
            elif item.primitive.kind == "circle":
                radius = item.primitive.radius or item.primitive.size[0] / 2
                pixels = round(
                    abs(
                        radius
                        * max(transform.scale[0], transform.scale[1])
                        / context.camera.width
                        * context.viewport.width
                    )
                )
                draw.circle(surface, color, position, pixels)
                if item.material.outline is not None and item.material.outline_width:
                    draw.circle(
                        surface,
                        self._color(
                            modulate_color(item.material.outline, modulation),
                            item.material.opacity,
                        ),
                        position,
                        pixels,
                        round(item.material.outline_width),
                    )
            elif item.primitive.kind == "point":
                draw.circle(surface, color, position, 1)
                if item.material.outline is not None and item.material.outline_width:
                    draw.circle(
                        surface,
                        self._color(
                            modulate_color(item.material.outline, modulation),
                            item.material.opacity,
                        ),
                        position,
                        1,
                        round(item.material.outline_width),
                    )
            else:
                self._draw_failed = True
                self._diagnostics.report(
                    ("renderer", "primitive", item.key, item.primitive.kind),
                    "[Render] unsupported primitive %s for %s",
                    item.primitive.kind,
                    item.key,
                )
        except Exception as exc:  # noqa: BLE001 - backend draw failures are frame-local
            self._draw_failed = True
            failure_type = "texture" if item.material.texture_id is not None else "primitive"
            self._diagnostics.report(
                ("renderer", failure_type, item.key, type(exc).__name__),
                "[Render] draw failed for %s: %s",
                item.key,
                exc,
            )

    def _prepare_texture_for_transform(self, texture: Any, *, require_alpha: bool) -> Any:
        get_bitsize = cast(Callable[[], int] | None, getattr(texture, "get_bitsize", None))
        get_flags = cast(Callable[[], int] | None, getattr(texture, "get_flags", None))
        if not callable(get_bitsize):
            return texture
        bitsize = get_bitsize()
        alpha_flag = getattr(self.pygame, "SRCALPHA", 0)
        has_alpha = callable(get_flags) and bool(get_flags() & alpha_flag)
        if bitsize in (24, 32) and (not require_alpha or has_alpha):
            return texture
        get_size = cast(Callable[[], tuple[int, int]] | None, getattr(texture, "get_size", None))
        surface_factory = cast(Callable[..., Any] | None, getattr(self.pygame, "Surface", None))
        if not callable(get_size) or not callable(surface_factory):
            return texture
        try:
            converted = surface_factory(get_size(), flags=alpha_flag, depth=32)
            converted.blit(texture, (0, 0))
            return converted
        except Exception:  # noqa: BLE001 - backend conversion failures use the source texture
            return texture

    @staticmethod
    def _color(color: Color, opacity: float) -> tuple[int, ...]:
        values = tuple(round(value * 255) for value in (color.red, color.green, color.blue))
        alpha = round(color.alpha * opacity * 255)
        return (*values, alpha) if alpha < 255 else values

    @staticmethod
    def _tint(color: Color, tint: Color) -> Color:
        return Color(
            color.red * tint.red,
            color.green * tint.green,
            color.blue * tint.blue,
            color.alpha * tint.alpha,
        )

    def _tinted_texture(self, texture: Any, tint: Color) -> Any | None:
        """Return a non-mutating tinted copy, or None when Pygame cannot provide one."""
        if tint == Color(1.0, 1.0, 1.0, 1.0):
            return texture
        copy = getattr(texture, "copy", None)
        blend = getattr(self.pygame, "BLEND_RGBA_MULT", None)
        if not callable(copy) or blend is None:
            return None
        tinted = copy()
        tinted_fill = getattr(tinted, "fill", None)
        if not callable(tinted_fill):
            return None
        tinted_fill(self._color(tint, 1.0), special_flags=blend)
        return tinted

    def _font(self, descriptor: TextDescriptor) -> Any:
        return self._font_provider(descriptor.font, round(descriptor.size))

    def _default_font_provider(self, name: str, size: int) -> Any:
        return self.pygame.font.Font(None if name == "default" else name, size)

    def measure_text(self, descriptor: TextDescriptor) -> tuple[int, int]:
        font = self._font(descriptor)
        lines: list[str] = []
        for paragraph in descriptor.text.split("\n"):
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if (
                    descriptor.max_width is not None
                    and font.size(candidate)[0] > descriptor.max_width
                ):
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        if not lines:
            return (0, 0)
        line_height = font.size("Ag")[1]
        return (max((font.size(line)[0] for line in lines), default=0), line_height * len(lines))

    def draw_text(
        self,
        descriptor: TextDescriptor,
        position: tuple[int, int],
        opacity: float = 1.0,
    ) -> None:
        self._draw_text_to_surface(descriptor, position, opacity, self.surface)

    def _draw_text_to_surface(
        self,
        descriptor: TextDescriptor,
        position: tuple[int, int],
        opacity: float,
        surface: Any | None,
    ) -> None:
        if surface is None or not descriptor.text:
            return
        font = self._font(descriptor)
        lines: list[str] = []
        for paragraph in descriptor.text.split("\n"):
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if (
                    descriptor.max_width is not None
                    and font.size(candidate)[0] > descriptor.max_width
                ):
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        line_height = font.size("Ag")[1]
        for index, line in enumerate(lines):
            width = font.size(line)[0]
            x = position[0]
            if descriptor.align == "center":
                x -= width // 2
            elif descriptor.align == "right":
                x -= width
            rendered = font.render(line, True, self._color(descriptor.color, opacity))
            surface.blit(rendered, (x, position[1] + index * line_height))

    def draw_nine_slice(
        self,
        descriptor: NineSliceDescriptor,
        tint: Color,
        *,
        apply_tint: bool = False,
    ) -> None:
        self._draw_nine_slice_to_surface(
            descriptor,
            tint,
            apply_tint=apply_tint,
            surface=self.surface,
        )

    def _draw_nine_slice_to_surface(
        self,
        descriptor: NineSliceDescriptor,
        tint: Color,
        *,
        apply_tint: bool,
        surface: Any | None,
    ) -> None:
        if surface is None:
            return
        if self._resource_provider is None:
            self._draw_failed = True
            return
        texture = self._resource_provider(descriptor.texture_id)
        if texture is None:
            self._draw_failed = True
            return
        if apply_tint:
            texture = self._tinted_texture(texture, tint)
            if texture is None:
                self._draw_failed = True
                return
        destination = descriptor.geometry.resolve(descriptor.rect)
        source = None
        get_size = getattr(texture, "get_size", None)
        if callable(get_size):
            width, height = get_size()
            source_geometry = replace(descriptor.geometry, outset=Insets())
            source = source_geometry.resolve(Rect(0, 0, width, height))
        for index, patch in enumerate(destination):
            rect = patch.rect
            destination_rect = self._rect(
                (round(rect.x), round(rect.y), round(rect.width), round(rect.height))
            )
            try:
                if source is None:
                    surface.blit(texture, destination_rect)
                else:
                    source_rect = source[index].rect
                    surface.blit(
                        texture,
                        destination_rect,
                        self._rect(
                            (
                                round(source_rect.x),
                                round(source_rect.y),
                                round(source_rect.width),
                                round(source_rect.height),
                            )
                        ),
                    )
            except TypeError:
                surface.blit(texture, destination_rect)

    def draw_ui_commands(self, commands: tuple[Any, ...]) -> None:
        """Translate pure UI draw commands without exposing backend objects to models."""
        draw = getattr(self.pygame, "draw", None)
        if self.surface is None or draw is None:
            return
        for command in commands:
            if command.kind == "label":
                self.draw_text(
                    TextDescriptor(
                        command.text,
                        font=command.font,
                        size=command.font_size,
                        align=command.align,
                        max_width=command.rect.width or None,
                    ),
                    (round(command.rect.x), round(command.rect.y)),
                )
            elif command.kind == "button":
                palette = {
                    "normal": (55, 65, 90),
                    "hover": (75, 95, 135),
                    "pressed": (35, 45, 70),
                    "focused": (70, 110, 160),
                    "disabled": (45, 45, 50),
                }
                with suppress(Exception):
                    draw.rect(
                        self.surface,
                        palette.get(command.state, palette["normal"]),
                        self._rect(
                            (
                                round(command.rect.x),
                                round(command.rect.y),
                                round(command.rect.width),
                                round(command.rect.height),
                            )
                        ),
                    )
                self.draw_text(
                    TextDescriptor(command.text, size=16, align="center"),
                    (
                        round(command.rect.x + command.rect.width / 2),
                        round(command.rect.y + command.rect.height / 2),
                    ),
                )
            elif command.kind == "panel":
                if isinstance(command.nine_slice, NineSliceDescriptor):
                    self.draw_nine_slice(command.nine_slice, command.nine_slice.tint)
                else:
                    with suppress(Exception):
                        draw.rect(
                            self.surface,
                            (25, 30, 48),
                            self._rect(
                                (
                                    round(command.rect.x),
                                    round(command.rect.y),
                                    round(command.rect.width),
                                    round(command.rect.height),
                                )
                            ),
                        )


PygameRenderFrame = RenderFrame
