"""Primitive Pygame renderer kept separate from the renderer-neutral engine."""

from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import (
    Color,
    NineSliceDescriptor,
    RenderContext,
    RendererCapabilities,
    TextDescriptor,
)
from expra_engine.runtime.rendering import RenderFrame as ContractRenderFrame

__all__ = ("PygameRenderFrame", "PygameRenderer", "RenderFrame")


@dataclass(frozen=True)
class RenderFrame:
    """The renderer-facing state for one frame."""

    active_scene: Scene | None
    score: int = 0
    status: str = ""


@dataclass(frozen=True)
class _FallbackRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


class PygameRenderer:
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
            blend_mode=True,
            resize=True,
            headless=True,
        )

    def start(self, context: RenderContext) -> None:
        self.context = context

    def resize(self, viewport: Any) -> None:
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

    def stop(self) -> None:
        self._engine = None
        self.context = None

    def render(self, frame: ContractRenderFrame) -> None:
        """Render a backend-neutral frame of primitive descriptors."""
        context = self.context
        if context is None:
            return
        draw = getattr(self.pygame, "draw", None)
        if draw is None or self.surface is None:
            return
        with suppress(Exception):
            draw.rect(self.surface, (10, 14, 30), self._rect(self.arena_bounds))
        for item in frame.visible_items(context):
            transform = item.world_transform
            center = context.camera.project(transform.position, context.viewport)
            position = (round(center[0]), round(center[1]))
            color = self._color(self._tint(item.material.color, item.material.tint), item.material.opacity)
            try:
                if item.material.texture_id is not None:
                    if self._resource_provider is None:
                        continue
                    texture = self._resource_provider(item.material.texture_id)
                    if texture is None:
                        continue
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
                    self.surface.blit(texture, self._rect_from_center(position, width, height))
                    continue
                if item.text is not None:
                    self.draw_text(item.text, position, item.material.opacity)
                    continue
                if item.nine_slice is not None:
                    self.draw_nine_slice(item.nine_slice, item.material.tint)
                    continue
                if item.primitive.kind in ("rectangle", "rect"):
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
                    draw.rect(self.surface, color, self._rect_from_center(position, width, height))
                    if item.material.outline is not None and item.material.outline_width:
                        draw.rect(
                            self.surface,
                            self._color(item.material.outline, item.material.opacity),
                            self._rect_from_center(position, width, height),
                            round(item.material.outline_width),
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
                    draw.circle(self.surface, color, position, pixels)
                elif item.primitive.kind == "point":
                    draw.circle(self.surface, color, position, 1)
            except Exception:  # noqa: BLE001 - backend draw failures are frame-local
                pass
        if isinstance(frame.payload, RenderFrame):
            self.on_render(frame.payload)

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

    def _font(self, descriptor: TextDescriptor) -> Any:
        return self._font_provider(descriptor.font, round(descriptor.size))

    def _default_font_provider(self, name: str, size: int) -> Any:
        return self.pygame.font.Font(None if name == "default" else name, size)

    def measure_text(self, descriptor: TextDescriptor) -> tuple[int, int]:
        font = self._font(descriptor)
        return tuple(font.size(descriptor.text))

    def draw_text(
        self,
        descriptor: TextDescriptor,
        position: tuple[int, int],
        opacity: float = 1.0,
    ) -> None:
        if self.surface is None or not descriptor.text:
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
                if descriptor.max_width is not None and font.size(candidate)[0] > descriptor.max_width:
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
            self.surface.blit(rendered, (x, position[1] + index * line_height))

    def draw_nine_slice(self, descriptor: NineSliceDescriptor, tint: Color) -> None:
        if self.surface is None or self._resource_provider is None:
            return
        texture = self._resource_provider(descriptor.texture_id)
        if texture is None:
            return
        for patch in descriptor.geometry.resolve(descriptor.rect):
            rect = patch.rect
            self.surface.blit(
                texture,
                self._rect((round(rect.x), round(rect.y), round(rect.width), round(rect.height))),
            )

    def on_render(self, frame: RenderFrame) -> None:
        """Render one frame of scene primitives and HUD text."""
        draw = self.pygame.draw
        with suppress(Exception):
            draw.rect(self.surface, (10, 14, 30), self._rect(self.arena_bounds))
        scene = frame.active_scene
        if scene is not None:
            for entity in scene.entities_by_layer():
                if not entity.enabled:
                    continue
                transform = entity.get_component(TransformComponent)
                if transform is None or not transform.enabled:
                    continue
                try:
                    position = self._to_screen(transform.x, transform.y)
                except (OverflowError, ValueError, TypeError):
                    continue
                if not all(
                    math.isfinite(value)
                    for value in (*position, transform.scale_x, transform.scale_y)
                ):
                    continue
                if transform.scale_x == 0 or transform.scale_y == 0:
                    continue
                if entity.has_tag("player") or entity.name.lower() == "player":
                    width = round(20 * abs(transform.scale_x))
                    height = round(20 * abs(transform.scale_y))
                    rectangle = self._rect_from_center(position, width, height)
                    try:
                        draw.rect(self.surface, (48, 224, 255), rectangle)
                        angle = math.radians(transform.rotation)
                        direction = (
                            position[0] + round(math.cos(angle) * 16),
                            position[1] + round(math.sin(angle) * 16),
                        )
                        draw.line(self.surface, (255, 255, 255), position, direction)
                    except Exception:  # noqa: BLE001 - backend draw failures are frame-local
                        pass
                elif entity.has_tag("enemy"):
                    width = round(20 * abs(transform.scale_x))
                    height = round(20 * abs(transform.scale_y))
                    with suppress(Exception):
                        draw.rect(
                            self.surface,
                            (255, 72, 178),
                            self._rect_from_center(position, width, height),
                        )
                elif entity.has_tag("target") or entity.name.lower() == "target":
                    radius = round(8 * (abs(transform.scale_x) + abs(transform.scale_y)) / 2)
                    with suppress(Exception):
                        draw.circle(self.surface, (255, 72, 178), position, radius)
                elif entity.has_tag("projectile"):
                    radius = round(8 * (abs(transform.scale_x) + abs(transform.scale_y)) / 2)
                    with suppress(Exception):
                        draw.circle(self.surface, (245, 248, 255), position, radius)

        self._draw_text(f"Score: {frame.score}", (16, 12))
        if frame.status:
            self._draw_text(frame.status, (16, 44))

    def _draw_text(self, text: str, position: tuple[int, int]) -> None:
        if self.font is None or self.surface is None:
            return
        try:
            rendered = self.font.render(text, True, (245, 248, 255))
            self.surface.blit(rendered, position)
        except Exception:  # noqa: BLE001 - backend/font failures are frame-local
            pass

    @staticmethod
    def _validate_bounds(bounds: tuple[float, float, float, float], name: str) -> None:
        try:
            values = tuple(float(value) for value in bounds)
            _, _, width, height = values
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must contain four finite values") from exc
        if not all(math.isfinite(value) for value in values) or width <= 0 or height <= 0:
            raise ValueError(f"{name} must have finite positive dimensions")

    def _to_screen(self, x: float, y: float) -> tuple[int, int]:
        world_x, world_y, world_width, world_height = self.world_bounds
        arena_x, arena_y, arena_width, arena_height = self.arena_bounds
        return (
            round(arena_x + (x - world_x) / world_width * arena_width),
            round(arena_y + (y - world_y) / world_height * arena_height),
        )

    def _rect(self, rectangle: tuple[int, int, int, int]) -> Any:
        rect_type = getattr(self.pygame, "Rect", None)
        return rect_type(*rectangle) if rect_type is not None else _FallbackRect(*rectangle)

    def _rect_from_center(self, center: tuple[int, int], width: int, height: int) -> Any:
        return self._rect((center[0] - width // 2, center[1] - height // 2, width, height))


PygameRenderFrame = RenderFrame
