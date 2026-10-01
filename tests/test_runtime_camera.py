"""Shared resolved-camera behavior used by standalone and embedded Play."""

from __future__ import annotations

from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import OrthographicCamera
from expra_engine.runtime.runtime_camera import RuntimeCameraResolver
from expra_engine.runtime.world_policy import WorldCameraContext


def test_resolver_uses_parent_composed_target_and_preserves_camera_object() -> None:
    scene = Scene("placed Level", camera={"width": 40.0, "position_smoothing_enabled": True})
    root = scene.create_entity("Level root")
    root.add_component(TransformComponent(x=2000.0, y=40.0))
    player = scene.create_entity("Courier", entity_id="courier", parent_id=root.entity_id)
    player.add_component(TransformComponent(x=12.0, y=3.0))
    camera = OrthographicCamera(width=20.0, height=10.0)
    resolver = RuntimeCameraResolver(camera, camera_target_id="courier")

    resolver.step(SimpleNamespace(active_scene=scene, world_streaming_system=None), 0.016)

    assert resolver.camera is camera
    assert camera.width == 40.0
    assert camera.target_position == (2012.0, 43.0)
    assert camera.position != camera.target_position


def test_resolver_reports_actual_world_camera_pose_and_recenters_on_world_commit() -> None:
    scene = Scene("World")
    courier = scene.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent(x=20.0, y=10.0))
    context = WorldCameraContext(
        camera_id="world-camera:main",
        primary_level_id="forest",
        camera_context_level_id="forest",
        follow_target_entity_id="courier",
        active_level_ids=("forest",),
        effective_bounds=(0.0, 0.0, 200.0, 100.0),
        bounds_sources=("forest",),
    )
    reported: list[tuple[tuple[float, float], tuple[float, float]]] = []

    class WorldSystem:
        camera_context = context

        def report_camera_view(self, position, size) -> None:
            reported.append((position, size))

    camera = OrthographicCamera(width=20.0, height=10.0)
    camera.position_smoothing_enabled = True
    resolver = RuntimeCameraResolver(camera)
    engine = SimpleNamespace(active_scene=scene, world_streaming_system=WorldSystem())

    resolver.step(engine, 0.016)

    assert camera.target_position == (20.0, 10.0)
    assert camera.limit_right == 200.0
    assert reported[-1] == (camera.position[:2], (camera.width, camera.height))

    context = WorldCameraContext(
        camera_id="world-camera:main",
        primary_level_id="forest",
        camera_context_level_id="forest",
        follow_target_entity_id="courier",
        active_level_ids=("forest",),
        effective_bounds=(100.0, 0.0, 300.0, 100.0),
        bounds_sources=("forest",),
        recenter_generation=1,
    )
    engine.world_streaming_system.camera_context = context
    courier.get_component(TransformComponent).x = 120.0
    camera.position = (900.0, 700.0)

    resolver.step(engine, 0.016)

    assert camera.limit_left == 100.0
    assert camera.position[:2] == camera.target_position == (120.0, 10.0)
    assert reported[-1] == (camera.position[:2], (camera.width, camera.height))
