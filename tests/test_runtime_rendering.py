"""Tests for backend-neutral, orthographic renderer contracts."""

from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

from expra_engine.runtime.rendering import (
    Color,
    MaterialDescriptor,
    NineSliceDescriptor,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    Renderer,
    RendererCapabilities,
    RenderFrame,
    RenderItem,
    RenderPhase,
    TextDescriptor,
    Transform,
    Viewport,
)


def test_contract_values_are_immutable_and_validate_finite_inputs() -> None:
    color = Color(0.1, 0.2, 0.3, 1.0)
    assert color == Color(0.1, 0.2, 0.3)
    with pytest.raises(FrozenInstanceError):
        color.red = 1.0  # type: ignore[misc]
    with pytest.raises(ValueError):
        Viewport(0, 0, 0, 100)
    with pytest.raises(ValueError):
        Transform(position=(float("nan"), 0.0, 0.0))
    with pytest.raises(ValueError):
        Color(2.0, 0.0, 0.0)


def test_orthographic_camera_maps_world_coordinates_into_viewport() -> None:
    camera = OrthographicCamera(position=(10.0, 20.0), width=20.0, height=10.0)
    viewport = Viewport(100, 50, 400, 200)

    assert camera.project((10.0, 20.0), viewport) == (300.0, 150.0)
    assert camera.project((0.0, 25.0), viewport) == (100.0, 50.0)
    assert camera.project((20.0, 15.0), viewport) == (500.0, 250.0)


def test_render_frame_culls_items_outside_orthographic_depth_range() -> None:
    context = RenderContext(
        Viewport(0, 0, 100, 100),
        OrthographicCamera(width=10, height=10, near=-2, far=3),
    )
    primitive = PrimitiveDescriptor("point")
    items = (
        RenderItem("near", primitive, Transform(position=(0, 0, -2))),
        RenderItem("far", primitive, Transform(position=(0, 0, 3))),
        RenderItem("behind", primitive, Transform(position=(0, 0, -2.1))),
        RenderItem("beyond", primitive, Transform(position=(0, 0, 3.1))),
    )

    assert [item.key for item in RenderFrame(items).visible_items(context)] == ["near", "far"]


def test_render_frame_culls_items_outside_viewport_and_keeps_boundary() -> None:
    context = RenderContext(Viewport(0, 0, 100, 100), OrthographicCamera(width=10, height=10))
    primitive = PrimitiveDescriptor("rectangle", size=(2.0, 2.0))
    inside = RenderItem("inside", primitive, Transform(position=(0.0, 0.0, 0.0)))
    boundary = RenderItem("boundary", primitive, Transform(position=(4.0, 0.0, 0.0)))
    outside = RenderItem("outside", primitive, Transform(position=(6.0, 0.0, 0.0)))

    frame = RenderFrame((outside, boundary, inside))

    assert [item.key for item in frame.visible_items(context)] == ["boundary", "inside"]


def test_parent_transforms_are_composed_before_projection() -> None:
    parent = Transform(position=(10.0, 5.0, 2.0), scale=(2.0, 3.0, 1.0))
    child = Transform(position=(1.0, 2.0, 4.0), scale=(0.5, 2.0, 1.0))
    item = RenderItem(
        "child",
        PrimitiveDescriptor("rectangle", size=(2.0, 2.0)),
        child,
        parent=parent,
    )

    assert item.world_transform.position == (12.0, 11.0, 6.0)
    assert item.world_transform.scale == (1.0, 6.0, 1.0)


def test_parent_scale_is_composed_into_child_depth() -> None:
    item = RenderItem(
        "child",
        PrimitiveDescriptor("point"),
        Transform(position=(0, 0, 2)),
        parent=Transform(position=(0, 0, 5), scale=(1, 1, 3)),
    )

    assert item.world_transform.position[2] == 11


def test_items_are_sorted_by_phase_depth_layer_then_insertion_order() -> None:
    primitive = PrimitiveDescriptor("point")
    items = (
        RenderItem("last", primitive, Transform(), phase=RenderPhase.TRANSPARENT, layer=1),
        RenderItem("first", primitive, Transform(), phase=RenderPhase.OPAQUE, layer=2),
        RenderItem("same-a", primitive, Transform(), phase=RenderPhase.OPAQUE, layer=2),
        RenderItem("behind", primitive, Transform(position=(0, 0, -1)), layer=2),
    )

    assert [item.key for item in RenderFrame(items).ordered_items()] == [
        "behind",
        "first",
        "same-a",
        "last",
    ]


def test_descriptors_and_renderer_protocol_are_backend_neutral() -> None:
    material = MaterialDescriptor(color=Color(1.0, 0.0, 0.5), opacity=0.8)
    assert material.color == Color(1.0, 0.0, 0.5, 1.0)
    assert RendererCapabilities(primitive=True, text=True).primitive
    assert get_type_hints(Renderer.start)["context"] is RenderContext
    assert not any(name in Renderer.__module__.lower() for name in ("pygame", "tk", "sdl"))


def test_viewport_rejects_non_finite_or_non_integral_coordinates() -> None:
    with pytest.raises(ValueError):
        Viewport(float("nan"), 0, 100, 100)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Viewport(0.5, 0, 100, 100)  # type: ignore[arg-type]


def test_camera_and_primitives_reject_non_finite_dimensions() -> None:
    with pytest.raises(ValueError):
        OrthographicCamera(width=float("nan"))
    with pytest.raises(ValueError):
        OrthographicCamera(near=float("inf"))
    with pytest.raises(ValueError):
        PrimitiveDescriptor("circle", radius=float("nan"))


def test_optional_material_and_draw_descriptors_validate_and_remain_immutable() -> None:
    material = MaterialDescriptor(
        texture_id="panel",
        tint=Color(0.5, 0.5, 1.0, 0.5),
        outline=Color(1.0, 0.0, 0.0),
        outline_width=2.0,
        blend_mode="add",
    )
    assert material.texture_id == "panel"
    assert material.tint.alpha == 0.5
    assert material.outline_width == 2.0
    assert TextDescriptor("", size=12, align="center").text == ""
    with pytest.raises(ValueError):
        MaterialDescriptor(opacity=1.1)
    with pytest.raises(ValueError):
        MaterialDescriptor(outline_width=-1)
    with pytest.raises(ValueError):
        TextDescriptor("x", size=0)
    with pytest.raises(ValueError):
        TextDescriptor("x", max_width=0)
    with pytest.raises(ValueError):
        TextDescriptor("x", align="diagonal")


def test_nine_slice_descriptor_is_backend_neutral_and_uses_existing_geometry() -> None:
    from expra_engine.ui_model.geometry import Insets, Rect
    from expra_engine.ui_model.nine_slice import NineSlice

    descriptor = NineSliceDescriptor(
        "panel",
        Rect(0, 0, 100, 40),
        NineSlice(Insets(4, 5, 6, 7)),
    )
    assert len(descriptor.geometry.resolve(descriptor.rect)) == 9
    assert "pygame" not in NineSliceDescriptor.__module__
