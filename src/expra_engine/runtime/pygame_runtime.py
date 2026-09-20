"""Pygame-backed standalone loop for the renderer-neutral engine."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderContext,
    Renderer,
    RenderFrame,
    Viewport,
)

__all__ = ("PygameRuntime",)


class PygameRuntime:
    """Drive an :class:`Engine` without coupling it to Pygame.

    ``pygame_module``, ``clock``, and ``surface_factory`` are injectable so
    the loop can be tested without opening a window or importing Pygame.
    """

    def __init__(
        self,
        engine: Any,
        renderer: Renderer | None = None,
        pygame_module: Any | None = None,
        clock: Any | None = None,
        surface_factory: Callable[[tuple[int, int]], Any] | None = None,
        *,
        size: tuple[int, int] = (800, 600),
        frame_rate: int = 60,
        render_callback: Callable[[Any, Any], None] | None = None,
        frame_factory: Callable[[Any, float], RenderFrame] | None = None,
        camera: OrthographicCamera | None = None,
    ) -> None:
        if frame_rate <= 0:
            raise ValueError("frame_rate must be positive")
        self.engine = engine
        self.renderer = renderer
        self.pygame = (
            pygame_module if pygame_module is not None else importlib.import_module("pygame")
        )
        self.clock = clock or self.pygame.time.Clock()
        self._surface_factory = surface_factory or self.pygame.display.set_mode
        self.size = size
        self.frame_rate = frame_rate
        self.render_callback = render_callback
        self.frame_factory = frame_factory
        self.camera = camera or OrthographicCamera()
        self.surface: Any | None = None
        self._keys: set[Any] = set()
        self._running = False
        self._context: RenderContext | None = None

    @property
    def keys(self) -> frozenset[Any]:
        """Return the currently held backend key values."""
        return frozenset(self._keys)

    def is_key_down(self, key: Any) -> bool:
        """Return whether *key* is currently held."""
        return key in self._keys

    def stop(self) -> None:
        """Request that the loop leave after the current event batch."""
        self._running = False

    def run(self) -> None:
        """Run frames until a quit event or an explicit stop request."""
        try:
            init = getattr(self.pygame, "init", None)
            if init is not None:
                init()
            self.surface = self._surface_factory(self.size)
            self._context = RenderContext(Viewport(0, 0, *self.size), self.camera)
            if self.renderer is not None:
                set_surface = getattr(self.renderer, "set_surface", None)
                if set_surface is not None:
                    set_surface(self.surface)
                self.renderer.start(self._context)
            self._running = True
            dt = self.clock.tick(self.frame_rate) / 1000.0
            while self._running:
                self._poll_events()
                self.engine.tick(dt)
                if self.renderer is not None:
                    frame = (
                        self.frame_factory(self.engine, dt)
                        if self.frame_factory is not None
                        else RenderFrame(elapsed=dt)
                    )
                    self.renderer.render(frame)
                elif self.render_callback is not None:
                    self.render_callback(self.surface, self.engine)
                self.pygame.display.flip()
                if self._running:
                    dt = self.clock.tick(self.frame_rate) / 1000.0
        finally:
            self._running = False
            try:
                if self.renderer is not None:
                    self.renderer.stop()
            finally:
                self.pygame.quit()

    def _poll_events(self) -> None:
        for event in self.pygame.event.get():
            event_type = getattr(event, "type", None)
            if event_type == self.pygame.QUIT:
                self.stop()
                break
            elif event_type == getattr(self.pygame, "VIDEORESIZE", object()):
                width, height = event.size
                self.size = (width, height)
                self.surface = self._surface_factory(self.size)
                camera = self._context.camera if self._context is not None else self.camera
                self._context = RenderContext(Viewport(0, 0, width, height), camera)
                if self.renderer is not None:
                    set_surface = getattr(self.renderer, "set_surface", None)
                    if set_surface is not None:
                        set_surface(self.surface)
                    self.renderer.resize(self._context.viewport)
            elif event_type == self.pygame.KEYDOWN:
                self._keys.add(event.key)
            elif event_type == self.pygame.KEYUP:
                self._keys.discard(event.key)
