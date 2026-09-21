"""Pygame-backed standalone loop for the renderer-neutral engine."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderContext,
    Renderer,
    RenderFrame,
    Viewport,
)
from expra_engine.runtime.ui import GameCanvas, UIEvent

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
        camera_target_id: str | None = None,
        ui_root: GameCanvas | None = None,
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
        self.camera_target_id = camera_target_id
        self._camera_scene_id: str | None = None
        self.ui_root = ui_root
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
            if self.ui_root is not None:
                from expra_engine.runtime.ui import Viewport as UIViewport

                self.ui_root.layout(UIViewport(*self.size))
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
                if getattr(getattr(self.engine, "run_state", None), "value", None) == "edit":
                    self.stop()
                self._sync_camera_target()
                self.camera.update(dt)
                if self.renderer is not None:
                    frame = (
                        self.frame_factory(self.engine, dt)
                        if self.frame_factory is not None
                        else RenderFrame(elapsed=dt)
                    )
                    self.renderer.render(frame)
                    if self.ui_root is not None:
                        draw_ui = getattr(self.renderer, "draw_ui_commands", None)
                        if draw_ui is not None:
                            draw_ui(self.ui_root.draw_commands())
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

    def screen_to_world(self, point: tuple[float, float]) -> tuple[float, float]:
        """Convert runtime pixel coordinates through the active camera."""
        viewport = self._context.viewport if self._context is not None else Viewport(0, 0, *self.size)
        return self.camera.unproject(point, viewport)

    def _sync_camera_target(self) -> None:
        scene = getattr(self.engine, "active_scene", None)
        if scene is None:
            return
        if scene.scene_id != self._camera_scene_id:
            self._camera_scene_id = scene.scene_id
            settings = getattr(scene, "camera", {})
            if isinstance(settings, dict):
                if hasattr(settings, "apply_to"):
                    settings.apply_to(self.camera)
                else:
                    self.camera.apply_dict(settings)
                self.camera_target_id = getattr(settings, "target_entity_id", None) or self.camera_target_id
        if self.camera_target_id is None:
            return
        target = scene.find_entity(self.camera_target_id)
        transform = target.get_component(TransformComponent) if target is not None else None
        if target is not None and target.enabled and transform is not None and transform.enabled:
            self.camera.target_position = (transform.x, transform.y)

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
                if self.ui_root is not None:
                    from expra_engine.runtime.ui import Viewport as UIViewport

                    self.ui_root.layout(UIViewport(width, height))
            elif event_type == self.pygame.KEYDOWN:
                self._keys.add(event.key)
                handled = self.ui_root is not None and self.ui_root.dispatch(
                    UIEvent("key_down", key=self._key_name(event.key))
                ) is not None
                if not handled:
                    self._signal_input("press", event.key)
            elif event_type == self.pygame.KEYUP:
                self._keys.discard(event.key)
                handled = self.ui_root is not None and self.ui_root.dispatch(
                    UIEvent("key_up", key=self._key_name(event.key))
                ) is not None
                if not handled:
                    self._signal_input("release", event.key)
            elif event_type == getattr(self.pygame, "MOUSEMOTION", object()):
                if self.ui_root is not None:
                    self.ui_root.dispatch(UIEvent("pointer_move", position=tuple(event.pos)))
            elif event_type == getattr(self.pygame, "MOUSEBUTTONDOWN", object()):
                handled = self.ui_root is not None and self.ui_root.dispatch(
                    UIEvent("pointer_down", position=tuple(event.pos), button=str(event.button))
                ) is not None
                if not handled:
                    self._signal_input("press", event.button)
            elif event_type == getattr(self.pygame, "MOUSEBUTTONUP", object()):
                handled = self.ui_root is not None and self.ui_root.dispatch(
                    UIEvent("pointer_up", position=tuple(event.pos), button=str(event.button))
                ) is not None
                if not handled:
                    self._signal_input("release", event.button)

    def _key_name(self, key: Any) -> str:
        key_api = getattr(self.pygame, "key", None)
        name = getattr(key_api, "name", None)
        return str(name(key)) if callable(name) else str(key)

    def _signal_input(self, phase: str, key: Any) -> None:
        """Translate a backend key event into the engine's semantic input map."""
        input_map = getattr(self.engine, "input_map", None)
        signal = getattr(self.engine, "signal", None)
        if input_map is None or signal is None:
            return
        key_name = str(key)
        key_api = getattr(self.pygame, "key", None)
        name = getattr(key_api, "name", None)
        if callable(name):
            key_name = str(name(key))
        physical = PhysicalInput("keyboard", key_name)
        transitions = getattr(input_map, phase)(physical)
        for action_event in transitions:
            signal(action_event)
