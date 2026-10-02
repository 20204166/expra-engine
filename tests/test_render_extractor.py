import json

import pytest

from expra_engine.core.component import (
    TransformComponent,
    component_from_dict,
    registered_component_types,
)
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene, WorldTransform2D
from expra_engine.editor.commands import SetComponentPropertyCommand
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
)
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.render_extractor import (
    RuntimeRenderFrameCache,
    extract_render_frame,
)
from expra_engine.runtime.rendering import (
    Color,
    MaterialDescriptor,
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderPhase,
    Transform,
    Viewport,
)
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.visual_components import (
    PrimitiveComponent,
    SpriteComponent,
    TextComponent,
)


def test_visual_components_round_trip_as_additive_json_payloads() -> None:
    components = (
        PrimitiveComponent(
            kind="rectangle",
            width=2.0,
            height=3.0,
            radius=0.5,
            fill=Color(0.1, 0.2, 0.3, 0.4),
            outline=Color(1.0, 1.0, 1.0),
            outline_width=0.25,
            layer=2,
            visible=False,
        ),
        SpriteComponent("ship.png", tint=Color(0.2, 0.3, 0.4, 0.5), width=4.0, height=5.0),
        TextComponent(
            "", font="mono", size=18.0, color=Color(0.9, 0.8, 0.7), max_width=120.0, align="right"
        ),
    )

    for component in components:
        payload = component.to_dict()
        assert json.loads(json.dumps(payload)) == payload
        loaded = component_from_dict(payload)
        assert loaded.to_dict() == payload
        assert payload["type"] in dict(registered_component_types())


def test_visual_components_expose_registry_field_metadata() -> None:
    assert tuple(field.name for field in component_type_spec("primitive").fields) == (
        "kind",
        "width",
        "height",
        "radius",
        "fill",
        "outline",
        "outline_width",
        "layer",
        "visible",
    )
    assert tuple(field.name for field in component_type_spec("sprite").fields) == (
        "asset",
        "tint",
        "width",
        "height",
        "region",
        "centered",
        "offset",
        "flip_h",
        "flip_v",
        "layer",
        "visible",
    )
    assert tuple(field.name for field in component_type_spec("text").fields) == (
        "text",
        "font",
        "size",
        "color",
        "max_width",
        "align",
        "layer",
        "visible",
    )


def test_canvas_modulation_is_registered_with_editor_metadata() -> None:
    assert tuple(field.name for field in component_type_spec("canvas_modulate").fields) == (
        "color",
        "enabled",
    )
    component = component_from_dict(
        {"type": "canvas_modulate", "color": [0.2, 0.3, 0.4, 0.5], "enabled": False}
    )
    assert component.to_dict() == {
        "type": "canvas_modulate",
        "color": [0.2, 0.3, 0.4, 0.5],
        "enabled": False,
    }


def test_render_frame_defaults_to_neutral_white_modulation() -> None:
    assert RenderFrame().modulation == Color(1.0, 1.0, 1.0, 1.0)


def test_extractor_keeps_existing_materials_and_resolves_modulation_once() -> None:
    scene = Scene("modulated")
    entity = scene.create_entity("visual")
    entity.add_component(PrimitiveComponent(fill=Color(0.8, 0.6, 0.4, 0.5)))
    entity.add_component(CanvasModulateComponent((0.5, 0.5, 0.5, 0.5)))

    frame = extract_render_frame(scene)

    assert frame.modulation == Color(0.5, 0.5, 0.5, 0.5)
    assert frame.items[0].material == MaterialDescriptor(
        color=Color(0.8, 0.6, 0.4, 0.5),
    )


def test_runtime_visibility_culling_is_conservative_for_renderable_components() -> None:
    scene = Scene("runtime culling")
    visible = scene.create_entity("visible", entity_id="visible")
    visible.add_component(TransformComponent(x=4.5))
    visible.add_component(
        PrimitiveComponent("polygon", points=((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
    )
    outside = scene.create_entity("outside", entity_id="outside")
    outside.add_component(TransformComponent(x=100.0, y=100.0))
    outside.add_component(PrimitiveComponent("rectangle", width=1.0, height=1.0))
    text = scene.create_entity("text", entity_id="text")
    text.add_component(TransformComponent(x=100.0, y=100.0))
    text.add_component(TextComponent("unbounded label"))
    context = RenderContext(
        Viewport(0, 0, 400, 300),
        OrthographicCamera(width=10.0, height=7.5),
    )

    unculled = extract_render_frame(scene)
    expected_visible = {
        item.key for item in unculled.items if item.is_visible(context)
    }
    culled = extract_render_frame(scene, visibility_context=context)

    actual = {item.key for item in culled.items}
    assert expected_visible <= actual
    assert "visible" in actual
    assert "outside" not in actual
    assert "text" in actual


def test_runtime_render_cache_skips_static_scene_scan_and_refreshes_dirty_entities(
    monkeypatch,
) -> None:
    scene = Scene("cached runtime culling")
    visible = scene.create_entity("visible", entity_id="visible")
    visible.add_component(TransformComponent())
    visible.add_component(PrimitiveComponent("rectangle"))
    moving_into_view = scene.create_entity("moving", entity_id="moving")
    moving_transform = TransformComponent(x=100.0, y=100.0)
    moving_into_view.add_component(moving_transform)
    moving_into_view.add_component(PrimitiveComponent("circle"))
    context = RenderContext(
        Viewport(0, 0, 400, 300),
        OrthographicCamera(width=10.0, height=7.5),
    )
    cache = RuntimeRenderFrameCache()

    initial = cache.extract(scene, context=context)
    assert {item.key for item in initial.items} == {"visible", "moving"}

    def unexpected_scene_scan():
        raise AssertionError("cached extraction should query candidates, not scan Scene.entities")

    monkeypatch.setattr(scene, "iter_entities", unexpected_scene_scan)
    static_frame = cache.extract(scene, context=context)
    assert {item.key for item in static_frame.items} == {"visible"}

    moving_transform.x = 0.0
    moving_transform.y = 0.0
    updated = cache.extract(scene, context=context)
    assert {item.key for item in updated.items} == {"visible", "moving"}


def test_runtime_render_cache_samples_the_current_frame_for_visible_animations() -> None:
    scene = Scene("animated cache")
    entity = scene.create_entity("animated", entity_id="animated")
    frames = SpriteFrames2D(
        {
            "walk": SpriteAnimation2D(
                (
                    SpriteFrame2D("first.png", region=SpriteRegion(0, 0, 8, 8)),
                    SpriteFrame2D("second.png", region=SpriteRegion(8, 0, 8, 8)),
                ),
                speed_fps=10.0,
            )
        }
    )
    component = AnimatedSprite2DComponent(frames, animation="walk")
    entity.add_component(component)
    player = AnimatedSpritePlayer2D(component)
    player.play()
    context = RenderContext(
        Viewport(0, 0, 400, 300),
        OrthographicCamera(width=10.0, height=7.5),
    )
    cache = RuntimeRenderFrameCache()

    initial = cache.extract(scene, context=context, animated_players={component: player})
    assert initial.items[0].material.texture_id == "first.png"

    player.advance(0.1)
    updated = cache.extract(scene, context=context, animated_players={component: player})

    assert updated.items[0].material.texture_id == "second.png"


def test_primitive_color_assignments_are_normalized_before_render_extraction() -> None:
    primitive = PrimitiveComponent()
    primitive.fill = (0.2, 0.4, 0.6, 0.8)
    primitive.outline = [0.9, 0.7, 0.5, 1.0]
    scene = Scene("primitive color assignment")
    scene.create_entity("shape").add_component(primitive)

    item = extract_render_frame(scene).items[0]

    assert primitive.fill == Color(0.2, 0.4, 0.6, 0.8)
    assert primitive.outline == Color(0.9, 0.7, 0.5, 1.0)
    assert item.material.color == Color(0.2, 0.4, 0.6, 0.8)
    assert item.material.outline == Color(0.9, 0.7, 0.5, 1.0)
    assert primitive.to_dict()["fill"] == [0.2, 0.4, 0.6, 0.8]


def test_invalid_primitive_color_assignment_preserves_previous_typed_value() -> None:
    primitive = PrimitiveComponent(fill=(0.1, 0.2, 0.3))
    previous_fill = primitive.fill
    previous_outline = primitive.outline

    with pytest.raises(ValueError, match="color must contain 3 or 4 values"):
        primitive.fill = (0.4, 0.5)
    with pytest.raises(ValueError, match="color must contain 3 or 4 values"):
        primitive.outline = (0.4, 0.5)

    assert primitive.fill is previous_fill
    assert primitive.outline is previous_outline


def test_visual_components_reject_non_finite_values_but_allow_backend_neutral_colors() -> None:
    with pytest.raises(ValueError):
        PrimitiveComponent("rectangle", width=float("nan"))
    with pytest.raises(ValueError):
        SpriteComponent("ship.png", height=float("inf"))
    with pytest.raises(ValueError):
        TextComponent("score", size=float("-inf"))


def test_sprite_component_rejects_fractional_region_values() -> None:
    with pytest.raises(ValueError, match="region must contain integer pixel values"):
        SpriteComponent("ship.png", region=(1.5, 2, 3, 4))


def test_extractor_composes_transforms_and_orders_phase_layer_and_entity_stably() -> None:
    scene = Scene("visuals")
    parent = scene.create_entity("parent", entity_id="parent", layer=1)
    parent.add_component(TransformComponent(x=10.0, y=5.0, rotation=90.0, scale_x=2.0, scale_y=2.0))
    child = scene.create_entity("child", entity_id="child", parent_id=parent.entity_id)
    child.add_component(TransformComponent(x=1.0, y=0.0))
    child.add_component(PrimitiveComponent("rectangle", width=2.0, height=2.0, layer=1))
    first = scene.create_entity("first", entity_id="first")
    first.add_component(PrimitiveComponent("rectangle", layer=3))
    second = scene.create_entity("second", entity_id="second")
    second.add_component(PrimitiveComponent("rectangle", layer=3))
    transparent = scene.create_entity("transparent", entity_id="transparent")
    transparent.add_component(
        PrimitiveComponent("rectangle", fill=Color(1.0, 1.0, 1.0, 0.5), layer=-1)
    )

    frame = extract_render_frame(scene, elapsed=1.25)

    assert frame.elapsed == 1.25
    assert [item.key for item in frame.ordered_items()] == [
        "child",
        "first",
        "second",
        "transparent",
    ]
    child_item = next(item for item in frame.items if item.key == "child")
    assert child_item.world_transform.position == (10.0, 7.0, 0.0)
    assert child_item.phase is RenderPhase.OPAQUE


def test_extractor_can_sample_runtime_interpolated_world_transforms() -> None:
    scene = Scene("animated")
    entity = scene.create_entity("moving", entity_id="moving")
    entity.add_component(TransformComponent(x=10.0))
    entity.add_component(PrimitiveComponent("rectangle"))
    interpolator = TransformInterpolator()
    interpolator.begin_tick()
    interpolator.capture("moving", Transform())
    interpolator.end_tick()
    interpolator.begin_tick()
    interpolator.capture("moving", Transform(position=(10.0, 0.0, 0.0)))
    interpolator.end_tick()

    frame = extract_render_frame(scene, interpolator=interpolator, interpolation_fraction=0.5)

    assert frame.items[0].transform.position == pytest.approx((5.0, 0.0, 0.0))


def test_static_render_extraction_uses_scene_world_transform_owner(monkeypatch) -> None:
    scene = Scene("world pose owner")
    entity = scene.create_entity("marker", entity_id="marker")
    entity.add_component(TransformComponent(x=1.0, y=2.0))
    entity.add_component(PrimitiveComponent("rectangle"))
    monkeypatch.setattr(
        scene,
        "world_transform",
        lambda entity_id: WorldTransform2D((30.0, 40.0), 15.0, (2.0, 3.0)),
    )

    item = extract_render_frame(scene).items[0]

    assert item.transform.position == (30.0, 40.0, 0.0)
    assert item.transform.rotation == 15.0
    assert item.transform.scale == (2.0, 3.0, 1.0)


def test_static_sprite_maps_region_offset_centering_and_flips() -> None:
    scene = Scene("static sprite")
    entity = scene.create_entity("ship", entity_id="ship")
    entity.add_component(
        SpriteComponent(
            "assets://ship.png",
            region=SpriteRegion(4, 8, 16, 12),
            offset=(1.5, -2.0),
            centered=False,
            flip_h=True,
            flip_v=True,
        )
    )

    item = extract_render_frame(scene).items[0]

    assert item.material.source_region == SpriteRegion(4, 8, 16, 12)
    assert item.sprite_offset == (1.5, -2.0)
    assert item.sprite_centered is False
    assert item.sprite_flip_h is True
    assert item.sprite_flip_v is True


def test_static_sprite_accepts_legacy_payload_defaults() -> None:
    component = component_from_dict({"type": "sprite", "asset": "assets://ship.png"})

    assert isinstance(component, SpriteComponent)
    assert component.region is None
    assert component.offset == (0.0, 0.0)
    assert component.centered is True
    assert component.flip_h is False
    assert component.flip_v is False


def test_sprite_region_inspector_values_remain_typed_after_edit() -> None:
    component = SpriteComponent("assets://ship.png", region=SpriteRegion(4, 8, 16, 12))
    descriptor = next(
        field for field in component_type_spec("sprite").fields if field.name == "region"
    )

    edited = descriptor.convert(str(component.region), original=component.region)

    assert edited == (4.0, 8.0, 16.0, 12.0)
    assert descriptor.convert("-1, 2, 3, 4", original=component.region) is component.region
    scene = Scene("region edit")
    entity = scene.create_entity("ship", entity_id="ship")
    entity.add_component(component)
    SetComponentPropertyCommand(scene, "ship", SpriteComponent, "region", edited).execute()

    assert component.region == SpriteRegion(4, 8, 16, 12)
    assert component.to_dict()["region"] == [4, 8, 16, 12]


def test_extractor_skips_disabled_hidden_and_malformed_visuals_deterministically() -> None:
    scene = Scene("invalid")
    disabled = scene.create_entity("disabled", entity_id="disabled")
    disabled.add_component(PrimitiveComponent("rectangle", enabled=False))
    hidden = scene.create_entity("hidden", entity_id="hidden")
    hidden.add_component(PrimitiveComponent("rectangle", visible=False))
    unknown = scene.create_entity("unknown", entity_id="unknown")
    unknown.add_component(PrimitiveComponent("hexagon"))
    malformed = scene.create_entity("malformed", entity_id="malformed")
    malformed.add_component(PrimitiveComponent("rectangle", width=0.0))
    mixed = scene.create_entity("mixed", entity_id="mixed")
    mixed.add_component(PrimitiveComponent("hexagon"))
    mixed.add_component(PrimitiveComponent("rectangle"))
    valid = scene.create_entity("valid", entity_id="valid")
    valid.add_component(TextComponent("hello"))

    assert [item.key for item in extract_render_frame(scene).items] == ["mixed", "valid"]
