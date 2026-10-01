"""Camera-mounted HUD component, extraction, and pixel regressions."""

from __future__ import annotations

from math import inf, nan

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import (
    Level,
    Scene,
    SceneInstanceComponent,
    resolve_scene_instances,
)
from expra_engine.core.scene.document_codec import decode_protobuf_document, encode_protobuf
from expra_engine.runtime.camera_mount import CameraMountComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    Color,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderItem,
    RenderSpace,
    Transform,
    Viewport,
)
from expra_engine.runtime.visual_components import PrimitiveComponent
from tests.support.pixel_surface import color_bounds
from tests.support.pygame_renderer import make_renderer


def test_camera_mount_component_round_trips_with_inspector_schema() -> None:
    component = component_from_dict(
        {"type": "camera_mount", "mount": "top_right", "x": -12.0, "y": -8.0}
    )

    assert component.to_dict() == {
        "type": "camera_mount",
        "enabled": True,
        "mount": "top_right",
        "x": -12.0,
        "y": -8.0,
    }
    assert tuple(field.name for field in component_type_spec("camera_mount").fields) == (
        "mount",
        "x",
        "y",
        "enabled",
    )


@pytest.mark.parametrize("mount", ["left", "middle", "TOP_LEFT", ""])
def test_camera_mount_rejects_unknown_named_anchor(mount: str) -> None:
    with pytest.raises(ValueError, match="mount"):
        CameraMountComponent(mount=mount)


@pytest.mark.parametrize(("x", "y"), [(inf, 0.0), (0.0, nan)])
def test_camera_mount_rejects_non_finite_offsets(x: float, y: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        CameraMountComponent(x=x, y=y)


def test_camera_mount_rejects_bool_offsets_and_non_bool_enabled() -> None:
    with pytest.raises(ValueError, match="numeric"):
        CameraMountComponent(x=True)
    with pytest.raises(ValueError, match="enabled"):
        CameraMountComponent(enabled=1)


def test_camera_mount_round_trips_in_a_level_document() -> None:
    level = Level("HUD Level")
    root = level.create_entity("HUD")
    root.add_component(CameraMountComponent("bottom_right", x=-16.0, y=16.0))

    restored = decode_protobuf_document(
        encode_protobuf(level), expected_kind=DocumentKind.LEVEL
    )

    component = restored.entities[0].get_component(CameraMountComponent)
    authored = root.get_component(CameraMountComponent)
    assert component is not None and authored is not None
    assert component.to_dict() == authored.to_dict()


def test_scene_instance_mount_is_inherited_by_resolved_children() -> None:
    source = Scene("Reusable HUD")
    panel = source.create_entity("Panel")
    panel.add_component(TransformComponent(x=32.0, y=4.0))
    panel.add_component(PrimitiveComponent("rectangle", width=8.0, height=8.0))
    level = Scene("Level")
    root = level.create_entity("HUD instance")
    root.add_component(TransformComponent(x=900.0, y=400.0))
    root.add_component(CameraMountComponent("bottom_right", x=-16.0, y=16.0))
    root.add_component(SceneInstanceComponent("scenes/hud.scene.pb"))
    resolve_scene_instances(level, resolve_source=lambda _path: source)

    (item,) = extract_render_frame(level).items

    assert item.space is RenderSpace.VIEWPORT
    assert item.viewport_anchor == (1.0, 0.0)
    assert item.viewport_offset == (-16.0, 16.0)
    assert item.transform.position == (32.0, 4.0, 0.0)


def test_viewport_projection_uses_anchor_pixels_independent_of_camera_pose() -> None:
    viewport = Viewport(0, 0, 200, 100)
    item = RenderItem(
        "hud",
        PrimitiveDescriptor("rectangle", (8.0, 8.0)),
        Transform(position=(32.0, 4.0, 0.0)),
        space=RenderSpace.VIEWPORT,
        viewport_anchor=(0.0, 1.0),
        viewport_offset=(16.0, -12.0),
    )
    projected = []
    for camera in (
        OrthographicCamera(position=(0.0, 0.0), width=20.0, height=10.0),
        OrthographicCamera(position=(300.0, -90.0), width=80.0, height=45.0),
    ):
        camera.rotation = 0.6
        camera.offset = (17.0, -8.0)
        context = RenderContext(viewport, camera)
        world_point = item.resolved_transform(context).position[:2]
        projected.append(camera.project(world_point, viewport))
    assert projected[0] == pytest.approx((48.0, 8.0))
    assert projected[1] == pytest.approx(projected[0])


def test_world_center_projection_uses_the_item_pose_without_transform_recomposition(
    monkeypatch,
) -> None:
    viewport = Viewport(0, 0, 200, 100)
    camera = OrthographicCamera(position=(10.0, 5.0), width=20.0, height=10.0)
    item = RenderItem(
        "world",
        PrimitiveDescriptor("rectangle", (8.0, 8.0)),
        Transform(position=(12.0, -2.0, 0.0)),
    )
    monkeypatch.setattr(
        Transform,
        "transform_point",
        lambda *_args, **_kwargs: pytest.fail("center projection must not recompose identity"),
    )

    assert item.project_point(RenderContext(viewport, camera)) == pytest.approx(
        camera.project((12.0, -2.0), viewport)
    )


def test_mount_extraction_uses_local_hierarchy_and_leaves_world_pose_unchanged() -> None:
    scene = Scene("HUD in a placed Level")
    level_root = scene.create_entity("Level root", entity_id="level-root")
    level_root.add_component(TransformComponent(x=2000.0, y=40.0))
    mount = scene.create_entity("HUD", entity_id="hud", parent_id=level_root.entity_id)
    mount.add_component(TransformComponent(x=300.0, y=-20.0))
    mount.add_component(CameraMountComponent("top_left", x=16.0, y=-12.0))
    marker = scene.create_entity("Marker", entity_id="marker", parent_id=mount.entity_id)
    marker.add_component(TransformComponent(x=32.0, y=4.0))
    marker.add_component(PrimitiveComponent("rectangle", width=8.0, height=8.0))
    before = scene.world_transform(marker.entity_id)

    (item,) = extract_render_frame(scene).items

    assert item.space is RenderSpace.VIEWPORT
    assert item.transform.position == (32.0, 4.0, 0.0)
    assert item.viewport_anchor == (0.0, 1.0)
    assert item.viewport_offset == (16.0, -12.0)
    assert scene.world_transform(marker.entity_id) == before


def test_deep_mount_traversal_is_linear_and_skips_discarded_world_poses(monkeypatch) -> None:
    scene = Scene("deep mounted hierarchy")
    root = scene.create_entity("HUD")
    root.add_component(CameraMountComponent("top_left"))
    parent = root
    depth = 40
    for index in range(depth):
        child = scene.create_entity(f"Node {index}", parent_id=parent.entity_id)
        child.add_component(TransformComponent(x=1.0))
        child.add_component(PrimitiveComponent("rectangle"))
        parent = child

    compose = Transform.compose
    calls = 0

    def count_compose(self, child):
        nonlocal calls
        calls += 1
        return compose(self, child)

    monkeypatch.setattr(Transform, "compose", count_compose)

    def world_transform_must_not_be_used(_entity_id: str):
        pytest.fail("mounted visuals do not need their discarded World pose")

    monkeypatch.setattr(scene, "world_transform", world_transform_must_not_be_used)

    frame = extract_render_frame(scene)

    assert len(frame.items) == depth
    assert calls <= depth


def test_pygame_hud_pixels_stay_fixed_while_world_camera_and_actor_move() -> None:
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        scene = Scene("pixel HUD")
        level_root = scene.create_entity("Level root")
        level_root.add_component(TransformComponent(x=800.0, y=-400.0))
        hud = scene.create_entity("HUD", parent_id=level_root.entity_id)
        hud.add_component(TransformComponent(x=250.0, y=90.0))
        hud.add_component(CameraMountComponent("top_left", x=16.0, y=-12.0))
        marker = scene.create_entity("HUD marker", parent_id=hud.entity_id)
        marker.add_component(TransformComponent(x=32.0, y=4.0))
        marker.add_component(
            PrimitiveComponent("rectangle", width=8.0, height=8.0, fill=Color(1.0, 0.0, 0.0))
        )
        courier = scene.create_entity("Courier", entity_id="courier")
        courier_transform = TransformComponent(x=-5.0, y=0.0)
        courier.add_component(courier_transform)
        courier.add_component(
            PrimitiveComponent("rectangle", width=4.0, height=4.0, fill=Color(0.0, 0.0, 1.0))
        )

        def draw(camera: OrthographicCamera):
            renderer, surface = make_renderer(
                pygame, (200, 100), flags=pygame.SRCALPHA, clear_color=None, camera=camera
            )
            renderer.render(extract_render_frame(scene))
            assert not renderer.draw_failed
            return surface

        camera = OrthographicCamera(width=20.0, height=10.0)
        before = draw(camera)
        hud_before = color_bounds(before, (255, 0, 0))
        courier_before = color_bounds(before, (0, 0, 255))
        courier_transform.x = 1.0
        actor_moved = draw(camera)
        assert color_bounds(actor_moved, (255, 0, 0)) == hud_before
        assert color_bounds(actor_moved, (0, 0, 255)) != courier_before
        camera.position = (4.0, 2.0)
        camera.zoom = 1.5
        camera_moved = draw(camera)
        assert color_bounds(camera_moved, (255, 0, 0)) == hud_before
        assert color_bounds(camera_moved, (0, 0, 255)) != color_bounds(
            actor_moved, (0, 0, 255)
        )
        camera.rotation = 0.25
        camera_rotated = draw(camera)
        assert color_bounds(camera_rotated, (255, 0, 0)) == hud_before
        assert color_bounds(camera_rotated, (0, 0, 255)) != color_bounds(
            camera_moved, (0, 0, 255)
        )
    finally:
        pygame.quit()


def test_viewport_mount_anchor_tracks_resize_without_scaling_content() -> None:
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        scene = Scene("resize HUD")
        root = scene.create_entity("HUD")
        root.add_component(CameraMountComponent("bottom_right", x=-16.0, y=16.0))
        marker = scene.create_entity("Marker", parent_id=root.entity_id)
        marker.add_component(
            PrimitiveComponent("rectangle", width=8.0, height=8.0, fill=Color(1.0, 0.0, 0.0))
        )
        camera = OrthographicCamera(width=20.0, height=10.0)

        def draw(size: tuple[int, int]):
            renderer, surface = make_renderer(
                pygame, size, flags=pygame.SRCALPHA, clear_color=None, camera=camera
            )
            renderer.render(extract_render_frame(scene))
            return surface

        small = color_bounds(draw((200, 100)), (255, 0, 0))
        large = color_bounds(draw((300, 180)), (255, 0, 0))
        assert (small[2] - small[0], small[3] - small[1]) == (
            large[2] - large[0],
            large[3] - large[1],
        )
        assert (large[0] - small[0], large[1] - small[1]) == (100, 80)
    finally:
        pygame.quit()
