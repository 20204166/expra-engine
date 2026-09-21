import json

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict, registered_component_types
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Color, RenderPhase
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent, TextComponent


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
        "asset", "tint", "width", "height", "layer", "visible"
    )
    assert tuple(field.name for field in component_type_spec("text").fields) == (
        "text", "font", "size", "color", "max_width", "align", "layer", "visible"
    )


def test_visual_components_reject_non_finite_values_but_allow_backend_neutral_colors() -> None:
    with pytest.raises(ValueError):
        PrimitiveComponent("rectangle", width=float("nan"))
    with pytest.raises(ValueError):
        SpriteComponent("ship.png", height=float("inf"))
    with pytest.raises(ValueError):
        TextComponent("score", size=float("-inf"))


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
