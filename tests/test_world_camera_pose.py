"""Runtime camera targets use the canonical World-space pose."""

from __future__ import annotations

from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import OrthographicCamera
from expra_engine.runtime.runtime_camera import RuntimeCameraResolver
from expra_engine.runtime.world_streaming import WorldCameraContext


def test_camera_follows_parent_composed_world_position() -> None:
    scene = Scene("Placed Level")
    root = scene.create_entity("World Origin")
    root.add_component(TransformComponent(x=2000.0, y=40.0))
    target = scene.create_entity("Streaming Anchor", entity_id="anchor", parent_id=root.entity_id)
    target.add_component(TransformComponent(x=12.0, y=3.0))
    camera = OrthographicCamera()
    resolver = RuntimeCameraResolver(camera, camera_target_id="anchor")

    resolver.sync(SimpleNamespace(active_scene=scene, world_streaming_system=None))

    assert camera.target_position == (2012.0, 43.0)


def test_camera_applies_late_initial_level_context_without_recreating_camera() -> None:
    scene = Scene("World")
    camera = OrthographicCamera()
    resolver = RuntimeCameraResolver(camera)
    engine = SimpleNamespace(active_scene=scene, world_streaming_system=None)

    resolver.sync(engine)
    scene.camera = {"position": [50.0, 60.0], "zoom": 2.0}
    resolver.sync(engine)

    assert resolver.camera is camera
    assert camera.position == (50.0, 60.0, 0.0)
    assert camera.zoom == 2.0


def test_world_camera_context_updates_bounds_and_follow_target_without_replacement() -> None:
    scene = Scene("World")
    root = scene.create_entity("World Origin")
    root.add_component(TransformComponent(x=200.0, y=30.0))
    target = scene.create_entity("Courier", entity_id="courier", parent_id=root.entity_id)
    target.add_component(TransformComponent(x=5.0, y=2.0))
    camera = OrthographicCamera()
    context = WorldCameraContext(
        "world-camera",
        "town",
        "town",
        "courier",
        ("town",),
        (0.0, 0.0, 300.0, 100.0),
        ("town",),
    )
    world_streaming = SimpleNamespace(camera_context=context)
    resolver = RuntimeCameraResolver(camera)
    engine = SimpleNamespace(active_scene=scene, world_streaming_system=world_streaming)

    resolver.sync(engine)

    assert camera.target_position == (205.0, 32.0)
    assert (camera.limit_left, camera.limit_bottom, camera.limit_right, camera.limit_top) == (
        0.0, 0.0, 300.0, 100.0
    )
    camera.zoom = 2.0
    context = WorldCameraContext(
        "world-camera",
        "forest",
        "town",
        "courier",
        ("town", "forest"),
        (0.0, 0.0, 500.0, 100.0),
        ("town", "forest"),
        recenter_generation=1,
    )
    world_streaming.camera_context = context
    camera.position = (900.0, 700.0, 0.0)

    resolver.sync(engine)

    assert resolver.camera is camera
    assert camera.zoom == 2.0
    assert camera.target_position == (205.0, 32.0)
    assert camera.limit_right == 500.0
    assert camera.position[:2] == (205.0, 32.0)
