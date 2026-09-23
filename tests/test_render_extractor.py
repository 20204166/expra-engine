import json

import pytest

from expra_engine.core.component import (
    TransformComponent,
    component_from_dict,
    registered_component_types,
)
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import SetComponentPropertyCommand
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    Color,
    MaterialDescriptor,
    RenderFrame,
    RenderPhase,
    Transform,
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
        TextComponent("", font="mono", size=18.0, color=Color(0.9, 0.8, 0.7), max_width=120.0, align="right"),
    )

    for component in components:
        payload = component.to_dict()
        assert json.loads(json.dumps(payload)) == payload
        loaded = component_from_dict(payload)
        assert loaded.to_dict() == payload
        assert payload["type"] in dict(registered_component_types())


def test_visual_components_expose_registry_field_metadata() -> None:
    assert tuple(field.name for field in component_type_spec("primitive").fields) == (
        "kind", "width", "height", "radius", "fill", "outline", "outline_width", "layer", "visible"
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
        "text", "font", "size", "color", "max_width", "align", "layer", "visible"
    )


def test_canvas_modulation_is_registered_with_editor_metadata() -> None:
    assert tuple(field.name for field in component_type_spec("canvas_modulate").fields) == (
        "color", "enabled"
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
        tint=Color(0.8, 0.6, 0.4, 0.5),
    )


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
    transparent.add_component(PrimitiveComponent("rectangle", fill=Color(1.0, 1.0, 1.0, 0.5), layer=-1))

    frame = extract_render_frame(scene, elapsed=1.25)

    assert frame.elapsed == 1.25
    assert [item.key for item in frame.ordered_items()] == ["child", "first", "second", "transparent"]
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
