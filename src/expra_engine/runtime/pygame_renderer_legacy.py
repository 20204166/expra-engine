"""Legacy tag-based Pygame drawing path.

Extracted from pygame_renderer.py to keep both modules under the repository's
900-line budget (see viewport_camera.py for the same pattern). Superseded by
the RenderItem/RenderPlan contract path (PygameRenderer.render()) but kept
for callers still passing a legacy RenderFrame as frame.payload -- see the
isinstance(frame.payload, RenderFrame) check in PygameRenderer._render_frame.
"""

from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import Color, RenderContext, Transform
from expra_engine.runtime.transform_interpolation import TransformInterpolator

__all__ = ("LegacyPygameRenderMixin", "RenderFrame", "_FallbackRect")


@dataclass(frozen=True)
class RenderFrame:
    """The renderer-facing state for one frame."""

    active_scene: Scene | None
    score: int = 0
    status: str = ""
    interpolator: TransformInterpolator | None = None
    interpolation_fraction: float = 0.0
    modulation: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0, 1.0))


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


class LegacyPygameRenderMixin:
    """Tag-based fallback drawing, mixed into ``PygameRenderer``.

    Provided by ``PygameRenderer.__init__``/``PygameRenderer._clear_surface``;
    declared here only so type checkers know this mixin's methods may use them.
    """

    pygame: Any
    surface: Any
    context: RenderContext | None
    world_bounds: tuple[float, float, float, float]
    arena_bounds: tuple[int, int, int, int]
    font: Any

    def _clear_surface(self, surface: Any, draw: Any) -> bool:
        raise NotImplementedError

    def on_render(self, frame: RenderFrame, *, clear: bool = True) -> None:
        """Render one frame of scene primitives and HUD text."""
        draw = self.pygame.draw
        if clear:
            self._clear_surface(self.surface, draw)
        scene = frame.active_scene
        if scene is not None:
            for entity in scene.entities_by_layer():
                if not entity.enabled:
                    continue
                transform = entity.get_component(TransformComponent)
                if transform is None or not transform.enabled:
                    continue
                sampled = Transform(
                    position=(transform.x, transform.y, 0.0),
                    rotation=transform.rotation,
                    scale=(transform.scale_x, transform.scale_y, 1.0),
                )
                if frame.interpolator is not None:
                    try:
                        sampled_transform = frame.interpolator.sample_world(
                            entity.entity_id,
                            frame.interpolation_fraction,
                        )
                    except KeyError:
                        pass
                    else:
                        sampled = sampled_transform
                try:
                    position = self._legacy_project(sampled.position[0], sampled.position[1])
                except (OverflowError, ValueError, TypeError):
                    continue
                if not all(
                    math.isfinite(value)
                    for value in (*position, sampled.scale[0], sampled.scale[1])
                ):
                    continue
                if sampled.scale[0] == 0 or sampled.scale[1] == 0:
                    continue
                if entity.has_tag("player") or entity.name.lower() == "player":
                    try:
                        self._draw_legacy_box(
                            self._legacy_color((48, 224, 255), frame.modulation),
                            sampled.position[0],
                            sampled.position[1],
                            20 * abs(sampled.scale[0]),
                            20 * abs(sampled.scale[1]),
                            sampled.rotation,
                        )
                        angle = math.radians(sampled.rotation)
                        direction = self._legacy_project(
                            sampled.position[0] + math.cos(angle) * 16,
                            sampled.position[1] + math.sin(angle) * 16,
                        )
                        draw.line(
                            self.surface,
                            self._legacy_color((255, 255, 255), frame.modulation),
                            position,
                            direction,
                        )
                    except Exception:  # noqa: BLE001 - backend draw failures are frame-local
                        pass
                elif entity.has_tag("enemy"):
                    with suppress(Exception):
                        self._draw_legacy_box(
                            self._legacy_color((255, 72, 178), frame.modulation),
                            sampled.position[0],
                            sampled.position[1],
                            20 * abs(sampled.scale[0]),
                            20 * abs(sampled.scale[1]),
                            sampled.rotation,
                        )
                elif entity.has_tag("target") or entity.name.lower() == "target":
                    radius = self._legacy_radius(
                        8 * (abs(sampled.scale[0]) + abs(sampled.scale[1])) / 2
                    )
                    with suppress(Exception):
                        draw.circle(
                            self.surface,
                            self._legacy_color((255, 72, 178), frame.modulation),
                            position,
                            radius,
                        )
                elif entity.has_tag("projectile"):
                    radius = self._legacy_radius(
                        8 * (abs(sampled.scale[0]) + abs(sampled.scale[1])) / 2
                    )
                    with suppress(Exception):
                        draw.circle(
                            self.surface,
                            self._legacy_color((245, 248, 255), frame.modulation),
                            position,
                            radius,
                        )

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
    def _legacy_color(rgb: tuple[int, int, int], modulation: Color) -> tuple[int, int, int]:
        return tuple(
            round(channel * factor)
            for channel, factor in zip(
                rgb, (modulation.red, modulation.green, modulation.blue), strict=True
            )
        )

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

    def _legacy_project(self, x: float, y: float) -> tuple[int, int]:
        if self.context is None:
            return self._to_screen(x, y)
        projected = self.context.camera.project((x, y), self.context.viewport)
        return round(projected[0]), round(projected[1])

    def _legacy_radius(self, world_radius: float) -> int:
        if self.context is None:
            return round(world_radius)
        camera = self.context.camera
        return round(
            world_radius
            * min(
                self.context.viewport.width / camera.width,
                self.context.viewport.height / camera.height,
            )
        )

    def _draw_legacy_box(
        self,
        color: tuple[int, ...],
        x: float,
        y: float,
        width: float,
        height: float,
        rotation: float,
    ) -> None:
        draw = self.pygame.draw
        if self.context is None:
            draw.rect(
                self.surface,
                color,
                self._rect_from_center(self._legacy_project(x, y), round(width), round(height)),
            )
            return
        angle = math.radians(rotation)
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        corners = []
        for local_x, local_y in (
            (-width / 2, -height / 2),
            (-width / 2, height / 2),
            (width / 2, height / 2),
            (width / 2, -height / 2),
        ):
            world_x = x + local_x * cos_angle - local_y * sin_angle
            world_y = y + local_x * sin_angle + local_y * cos_angle
            corners.append(self._legacy_project(world_x, world_y))
        if rotation or self.context.camera.rotation:
            polygon = getattr(draw, "polygon", None)
            if polygon is not None:
                polygon(self.surface, color, corners)
                return
        center = self._legacy_project(x, y)
        pixel_width = round(width / self.context.camera.width * self.context.viewport.width)
        pixel_height = round(height / self.context.camera.height * self.context.viewport.height)
        draw.rect(self.surface, color, self._rect_from_center(center, pixel_width, pixel_height))

    def _rect(self, rectangle: tuple[int, int, int, int]) -> Any:
        rect_type = getattr(self.pygame, "Rect", None)
        return rect_type(*rectangle) if rect_type is not None else _FallbackRect(*rectangle)

    def _rect_from_center(self, center: tuple[int, int], width: int, height: int) -> Any:
        return self._rect((center[0] - width // 2, center[1] - height // 2, width, height))
