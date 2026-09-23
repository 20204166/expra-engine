"""Tests for extracting screen effects through the canonical render boundary."""

from __future__ import annotations

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Color, RenderItem, RenderPhase, Transform
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureComponent,
    ScreenTextureDrawRequest,
    ScreenTextureFilter,
)
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.visual_components import PrimitiveComponent
from expra_engine.ui_model.geometry import Rect


def _effect(entry: object) -> RenderEffect:
    assert isinstance(entry, RenderEffect)
    return entry


def test_extractor_interleaves_visuals_and_screen_effects_without_polluting_items() -> None:
    scene = Scene("effects")
    first = scene.create_entity("first", entity_id="first")
    first.add_component(PrimitiveComponent("rectangle"))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    second = scene.create_entity("second", entity_id="second")
    second.add_component(PrimitiveComponent("rectangle"))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent())

    frame = extract_render_frame(scene)

    assert [item.key for item in frame.items] == ["first", "second"]
    assert [
        entry.key if isinstance(entry, RenderItem) else _effect(entry).request.entity_id
        for entry in frame.submissions
    ] == ["first", "capture", "second", "consumer"]


def test_extractor_preserves_component_insertion_order_in_submissions() -> None:
    scene = Scene("component order")
    entity = scene.create_entity("mixed", entity_id="mixed")
    entity.add_component(PrimitiveComponent("rectangle"))
    entity.add_component(BackBufferCopyComponent(copy_mode=BackBufferCopyMode.VIEWPORT))
    entity.add_component(PrimitiveComponent("circle"))
    entity.add_component(ScreenTextureComponent())

    frame = extract_render_frame(scene)

    assert [type(entry) for entry in frame.submissions] == [
        RenderItem,
        RenderEffect,
        RenderItem,
        RenderEffect,
    ]
    assert [
        type(_effect(entry).request)
        for entry in frame.submissions
        if isinstance(entry, RenderEffect)
    ] == [BackBufferCopyRequest, ScreenTextureDrawRequest]


def test_ordinary_scene_keeps_submissions_empty() -> None:
    scene = Scene("ordinary")
    entity = scene.create_entity("visual", entity_id="visual")
    entity.add_component(PrimitiveComponent("rectangle"))

    assert extract_render_frame(scene).submissions == ()


def test_effect_markers_store_phase_combined_layer_and_resolved_depth() -> None:
    scene = Scene("metadata")
    capture_entity = scene.create_entity("capture", entity_id="capture", layer=4)
    capture_entity.add_component(
        BackBufferCopyComponent(
            copy_mode="rect",
            rect=(-2.0, -3.0, 4.0, 5.0),
            capture_id="portal",
            layer=7,
            phase="overlay",
        )
    )
    consumer_entity = scene.create_entity("consumer", entity_id="consumer", layer=-2)
    consumer_entity.add_component(
        ScreenTextureComponent(
            capture_id="portal",
            width=8.0,
            height=6.0,
            uv_rect=(0.1, 0.2, 0.5, 0.6),
            filter="nearest_mipmap",
            lod=2.0,
            tint=Color(0.2, 0.3, 0.4, 0.5),
            opacity=0.75,
            layer=5,
            phase="transparent",
        )
    )

    interpolator = TransformInterpolator()
    interpolator.begin_tick()
    interpolator.capture(
        "capture",
        Transform(position=(3.0, 4.0, 2.5), rotation=15.0, scale=(2.0, 3.0, 1.0)),
    )
    interpolator.end_tick()

    frame = extract_render_frame(scene, interpolator=interpolator)
    capture_effect = _effect(frame.submissions[0])
    consumer_effect = _effect(frame.submissions[1])

    assert capture_effect.phase is RenderPhase.OVERLAY
    assert capture_effect.layer == 11
    assert capture_effect.request == BackBufferCopyRequest(
        "capture",
        "portal",
        BackBufferCopyMode.RECT,
        Transform(position=(3.0, 4.0, 2.5), rotation=15.0, scale=(2.0, 3.0, 1.0)),
        Rect(-2.0, -3.0, 4.0, 5.0),
    )
    assert consumer_effect.phase is RenderPhase.TRANSPARENT
    assert consumer_effect.layer == 3
    assert consumer_effect.request == ScreenTextureDrawRequest(
        "consumer",
        "portal",
        Transform(),
        8.0,
        6.0,
        Rect(0.1, 0.2, 0.5, 0.6),
        filter=ScreenTextureFilter.NEAREST_MIPMAP,
        lod=2.0,
        tint=Color(0.2, 0.3, 0.4, 0.5),
        opacity=0.75,
    )


def test_effects_use_the_same_resolved_parent_transform_as_ordinary_items() -> None:
    scene = Scene("hierarchy")
    parent = scene.create_entity("parent", entity_id="parent")
    parent.add_component(TransformComponent(x=10.0, y=5.0, rotation=90.0, scale_x=2.0, scale_y=2.0))
    child = scene.create_entity("child", entity_id="child", parent_id="parent")
    child.add_component(TransformComponent(x=1.0, rotation=10.0, scale_x=3.0, scale_y=4.0))
    child.add_component(PrimitiveComponent("rectangle"))
    child.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    child.add_component(ScreenTextureComponent())

    frame = extract_render_frame(scene)
    world = Transform(position=(10.0, 7.0, 0.0), rotation=100.0, scale=(6.0, 8.0, 1.0))

    assert frame.items[0].transform == world
    assert _effect(frame.submissions[1]).request.transform == world
    assert _effect(frame.submissions[2]).request.transform == world


def test_effects_use_interpolated_world_transform() -> None:
    scene = Scene("interpolated")
    entity = scene.create_entity("moving", entity_id="moving")
    entity.add_component(
        TransformComponent(x=10.0, y=20.0, rotation=90.0, scale_x=3.0, scale_y=5.0)
    )
    entity.add_component(PrimitiveComponent("rectangle"))
    entity.add_component(ScreenTextureComponent())

    interpolator = TransformInterpolator()
    interpolator.begin_tick()
    interpolator.capture("moving", Transform())
    interpolator.end_tick()
    interpolator.begin_tick()
    interpolator.capture(
        "moving",
        Transform(position=(10.0, 20.0, 1.0), rotation=90.0, scale=(3.0, 5.0, 1.0)),
    )
    interpolator.end_tick()

    frame = extract_render_frame(
        scene,
        interpolator=interpolator,
        interpolation_fraction=0.5,
    )
    expected = Transform(position=(5.0, 10.0, 0.5), rotation=45.0, scale=(2.0, 3.0, 1.0))

    assert frame.items[0].transform == expected
    assert _effect(frame.submissions[1]).request.transform == expected


def test_extractor_omits_disabled_entities_components_and_hidden_consumers() -> None:
    scene = Scene("filtered")
    disabled_entity = scene.create_entity("disabled entity", entity_id="disabled", enabled=False)
    disabled_entity.add_component(PrimitiveComponent("rectangle"))
    disabled_entity.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    disabled_entity.add_component(ScreenTextureComponent())

    disabled_components = scene.create_entity("disabled components", entity_id="components")
    disabled_components.add_component(PrimitiveComponent("rectangle"))
    disabled_components.add_component(BackBufferCopyComponent(enabled=False))
    disabled_components.add_component(ScreenTextureComponent(enabled=False))

    hidden = scene.create_entity("hidden", entity_id="hidden")
    hidden.add_component(ScreenTextureComponent(visible=False))

    visible_capture = scene.create_entity("visible capture", entity_id="visible-capture")
    visible_capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))

    frame = extract_render_frame(scene)

    assert [item.key for item in frame.items] == ["components"]
    assert [
        entry.key if isinstance(entry, RenderItem) else _effect(entry).request.entity_id
        for entry in frame.submissions
    ] == ["components", "visible-capture"]
    assert all(
        not isinstance(entry, RenderEffect) or entry.request.entity_id not in {"disabled", "hidden"}
        for entry in frame.submissions
    )


def test_malformed_effect_values_are_skipped_without_dropping_valid_visuals() -> None:
    scene = Scene("malformed")
    visual = scene.create_entity("visual", entity_id="visual")
    visual.add_component(PrimitiveComponent("rectangle"))

    bad_capture = scene.create_entity("bad capture", entity_id="bad-capture")
    capture_component = BackBufferCopyComponent(copy_mode="viewport")
    capture_component.capture_id = ""
    bad_capture.add_component(capture_component)

    bad_consumer = scene.create_entity("bad consumer", entity_id="bad-consumer")
    screen_component = ScreenTextureComponent()
    screen_component.width = 0.0
    bad_consumer.add_component(screen_component)

    valid_capture = scene.create_entity("valid capture", entity_id="valid-capture")
    valid_capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))

    frame = extract_render_frame(scene)

    assert [item.key for item in frame.items] == ["visual"]
    assert [
        entry.key if isinstance(entry, RenderItem) else _effect(entry).request.entity_id
        for entry in frame.submissions
    ] == ["visual", "valid-capture"]


def test_canvas_modulation_is_resolved_once_for_effect_frames() -> None:
    scene = Scene("modulated effects")
    entity = scene.create_entity("effect", entity_id="effect")
    entity.add_component(PrimitiveComponent("rectangle"))
    entity.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    entity.add_component(ScreenTextureComponent())
    entity.add_component(CanvasModulateComponent((0.2, 0.4, 0.6, 0.8)))

    frame = extract_render_frame(scene)

    assert frame.modulation == Color(0.2, 0.4, 0.6, 0.8)
    assert [type(entry) for entry in frame.submissions] == [RenderItem, RenderEffect, RenderEffect]
