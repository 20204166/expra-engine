"""Shared runtime Camera2D resolution for standalone and embedded Play loops."""

from __future__ import annotations

import json
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.rendering import OrthographicCamera

__all__ = ("RuntimeCameraResolver",)


class RuntimeCameraResolver:
    """Resolve configured and World camera targets into one live camera pose.

    The game-loop host owns frame timing and rendering. This class owns only
    the shared camera configuration/target/World-context interpretation.
    """

    def __init__(
        self,
        camera: OrthographicCamera,
        *,
        camera_target_id: str | None = None,
    ) -> None:
        if not isinstance(camera, OrthographicCamera):
            raise TypeError("camera must be an OrthographicCamera")
        self.camera = camera
        self.camera_target_id = camera_target_id
        self._camera_scene_id: str | None = None
        self._camera_settings_fingerprint: str | None = None
        self._world_camera_bounds: tuple[float, float, float, float] | None = None
        self._camera_recenter_generation = 0

    def sync(self, engine: Any) -> None:
        """Apply scene/World camera settings and update the live follow target."""
        scene = getattr(engine, "active_scene", None)
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

        world_system = getattr(engine, "world_streaming_system", None)
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
        elif self._world_camera_bounds is not None:
            self.camera.clear_limits()
            self._world_camera_bounds = None
            self._camera_recenter_generation = 0

        if self.camera_target_id is None:
            return
        target = scene.find_entity(self.camera_target_id)
        if target is None or not target.enabled:
            return
        transform = target.get_component(TransformComponent)
        if transform is None or not transform.enabled:
            return
        self.camera.target_position = scene.world_transform(target.entity_id).position
        recenter_generation = getattr(context, "recenter_generation", 0)
        if recenter_generation != self._camera_recenter_generation:
            target_position = self.camera.target_position
            self.camera.position = (
                target_position[0],
                target_position[1],
                self.camera.position[2],
            )
            self._camera_recenter_generation = recenter_generation

    def step(self, engine: Any, dt: float) -> None:
        """Resolve camera targets, advance motion, and report the resulting view."""
        self.sync(engine)
        self.camera.update(dt)
        world_system = getattr(engine, "world_streaming_system", None)
        report_camera_view = getattr(world_system, "report_camera_view", None)
        if callable(report_camera_view):
            report_camera_view(
                self.camera.position[:2],
                (self.camera.width, self.camera.height),
            )
