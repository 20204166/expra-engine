"""Primitive Pygame renderer kept separate from the renderer-neutral engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene

__all__ = ("PygameRenderer", "RenderFrame")


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
        surface: Any,
        *,
        screen_size: tuple[int, int] = (800, 600),
        world_bounds: tuple[float, float, float, float] = (0, 0, 100, 100),
        arena_bounds: tuple[int, int, int, int] | None = None,
        font_size: int = 24,
    ) -> None:
        self.pygame = pygame_module
        self.surface = surface
        self.screen_size = screen_size
        self.world_bounds = world_bounds
        self.arena_bounds = arena_bounds if arena_bounds is not None else (0, 0, *screen_size)
        self._validate_bounds(self.world_bounds, "world_bounds")
        self._validate_bounds(self.arena_bounds, "arena_bounds")
        try:
            self.font = pygame_module.font.Font(None, font_size)
        except Exception:  # noqa: BLE001 - backend/font failures must not abort a frame
            self.font = None
        self._engine: Any = None

    def start(self, engine: Any) -> None:
        """Attach to the runtime lifecycle without changing the Engine."""
        self._engine = engine

    def stop(self) -> None:
        self._engine = None

    def on_render(self, frame: RenderFrame) -> None:
        """Render one frame of scene primitives and HUD text."""
        draw = self.pygame.draw
        try:
            draw.rect(self.surface, (10, 14, 30), self._rect(self.arena_bounds))
        except Exception:  # noqa: BLE001 - backend draw failures are frame-local
            pass
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
                if not all(math.isfinite(value) for value in (*position, transform.scale_x, transform.scale_y)):
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
                elif entity.has_tag("target") or entity.name.lower() == "target":
                    radius = round(8 * (abs(transform.scale_x) + abs(transform.scale_y)) / 2)
                    try:
                        draw.circle(self.surface, (255, 72, 178), position, radius)
                    except Exception:  # noqa: BLE001 - backend draw failures are frame-local
                        pass

        self._draw_text(f"Score: {frame.score}", (16, 12))
        if frame.status:
            self._draw_text(frame.status, (16, 44))

    def _draw_text(self, text: str, position: tuple[int, int]) -> None:
        if self.font is None:
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
