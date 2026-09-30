"""Pygame-backed standalone loop for the renderer-neutral engine."""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.pygame_input import (
    keyboard_control_name,
    translate_axis_event,
    translate_event,
)
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
        self._camera_settings_fingerprint: str | None = None
        self._world_camera_bounds: tuple[float, float, float, float] | None = None
        self._camera_recenter_generation = 0
        self.ui_root = ui_root
        self.surface: Any | None = None
        self._transition_overlay: Any | None = None
        self._transition_overlay_size: tuple[int, int] | None = None
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
            joystick = getattr(self.pygame, "joystick", None)
            if joystick is not None:
                joystick_init = getattr(joystick, "init", None)
                if callable(joystick_init):
                    joystick_init()
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
                world_system = getattr(self.engine, "world_streaming_system", None)
                report_camera_view = getattr(world_system, "report_camera_view", None)
                if callable(report_camera_view):
                    report_camera_view(
                        self.camera.position[:2],
                        (self.camera.width, self.camera.height),
                    )
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
                self._draw_world_transition_overlay()
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
        viewport = (
            self._context.viewport if self._context is not None else Viewport(0, 0, *self.size)
        )
        return self.camera.unproject(point, viewport)

    def _draw_world_transition_overlay(self) -> None:
        """Present World FADE over the completed frame without renderer ownership."""
        if self.surface is None:
            return
        world_system = getattr(self.engine, "world_streaming_system", None)
        alpha = float(getattr(world_system, "transition_alpha", 0.0))
        if alpha <= 0.0:
            return
        if self._transition_overlay is None or self._transition_overlay_size != self.size:
            self._transition_overlay = self.pygame.Surface(self.size, self.pygame.SRCALPHA)
            self._transition_overlay.fill((0, 0, 0))
            self._transition_overlay_size = self.size
        self._transition_overlay.set_alpha(round(min(1.0, alpha) * 255))
        self.surface.blit(self._transition_overlay, (0, 0))

    def _sync_camera_target(self) -> None:
        scene = getattr(self.engine, "active_scene", None)
        if scene is None:
            return
        settings = getattr(scene, "camera", {})
        try:
            fingerprint = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            fingerprint = repr(settings)
        if (
            scene.scene_id != self._camera_scene_id
            or fingerprint != self._camera_settings_fingerprint
        ):
            self._camera_scene_id = scene.scene_id
            self._camera_settings_fingerprint = fingerprint
            if isinstance(settings, dict):
                if hasattr(settings, "apply_to"):
                    settings.apply_to(self.camera)
                else:
                    self.camera.apply_dict(settings)
                self.camera_target_id = (
                    getattr(settings, "target_entity_id", None) or self.camera_target_id
                )
        world_system = getattr(self.engine, "world_streaming_system", None)
        context = None
        if world_system is not None:
            context = getattr(world_system, "camera_context", None)
            if context is not None:
                if context.follow_target_entity_id is not None:
                    self.camera_target_id = context.follow_target_entity_id
                bounds = context.effective_bounds
                if bounds != self._world_camera_bounds:
                    if bounds is None:
                        self.camera.clear_limits()
                    else:
                        self.camera.set_limits(*bounds)
                    self._world_camera_bounds = bounds
        elif getattr(self, "_world_camera_bounds", None) is not None:
            self.camera.clear_limits()
            self._world_camera_bounds = None
            self._camera_recenter_generation = 0
        if self.camera_target_id is None:
            return
        target = scene.find_entity(self.camera_target_id)
        if target is None or not target.enabled:
            return
        transform = target.get_component(TransformComponent)
        if transform is not None and transform.enabled:
            self.camera.target_position = scene.world_transform(target.entity_id).position
            recenter_generation = getattr(context, "recenter_generation", 0)
            if recenter_generation != getattr(self, "_camera_recenter_generation", 0):
                target_position = self.camera.target_position
                self.camera.position = (
                    target_position[0],
                    target_position[1],
                    self.camera.position[2],
                )
                self._camera_recenter_generation = recenter_generation

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
                handled = (
                    self.ui_root is not None
                    and self.ui_root.dispatch(
                        UIEvent("key_down", key=keyboard_control_name(self.pygame, event.key))
                    )
                    is not None
                )
                if not handled:
                    self._signal_translated_input(event)
            elif event_type == self.pygame.KEYUP:
                self._keys.discard(event.key)
                handled = (
                    self.ui_root is not None
                    and self.ui_root.dispatch(
                        UIEvent("key_up", key=keyboard_control_name(self.pygame, event.key))
                    )
                    is not None
                )
                if not handled:
                    self._signal_translated_input(event)
            elif event_type == getattr(self.pygame, "MOUSEMOTION", object()):
                if self.ui_root is not None:
                    self.ui_root.dispatch(UIEvent("pointer_move", position=tuple(event.pos)))
            elif event_type == getattr(self.pygame, "MOUSEBUTTONDOWN", object()):
                handled = (
                    self.ui_root is not None
                    and self.ui_root.dispatch(
                        UIEvent("pointer_down", position=tuple(event.pos), button=str(event.button))
                    )
                    is not None
                )
                if not handled:
                    self._signal_translated_input(event)
            elif event_type == getattr(self.pygame, "MOUSEBUTTONUP", object()):
                handled = (
                    self.ui_root is not None
                    and self.ui_root.dispatch(
                        UIEvent("pointer_up", position=tuple(event.pos), button=str(event.button))
                    )
                    is not None
                )
                if not handled:
                    self._signal_translated_input(event)
            elif (
                event_type == getattr(self.pygame, "JOYBUTTONDOWN", object())
                or event_type == getattr(self.pygame, "JOYBUTTONUP", object())
            ):
                self._signal_translated_input(event)
            elif event_type == getattr(self.pygame, "JOYAXISMOTION", object()):
                translated = translate_axis_event(self.pygame, event)
                if translated is not None:
                    physical, value = translated
                    self._signal_axis(physical, value)

    def _signal_translated_input(self, event: Any) -> None:
        """Pass an unhandled Pygame event through the canonical input adapter."""
        translated = translate_event(self.pygame, event)
        if translated is not None:
            self._signal_input(*translated)

    def _signal_input(self, phase: str, physical: PhysicalInput) -> None:
        """Resolve a translated physical input through the engine's input map."""
        input_map = getattr(self.engine, "input_map", None)
        signal = getattr(self.engine, "signal", None)
        if input_map is None or signal is None:
            return
        transitions = getattr(input_map, phase)(physical)
        for action_event in transitions:
            signal(action_event)

    def _signal_axis(self, physical: PhysicalInput, value: float) -> None:
        """Update an analog action value from a translated physical axis."""
        input_map = getattr(self.engine, "input_map", None)
        set_axis = getattr(input_map, "set_axis", None)
        if set_axis is not None:
            set_axis(physical, value)
