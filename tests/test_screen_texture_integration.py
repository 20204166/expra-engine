"""Integration tests for screen-texture component registration and persistence."""

import json

import pytest

from expra_engine.core.component import component_from_dict, registered_component_types
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    ScreenTextureComponent,
)


def test_screen_components_register_for_direct_schema_lookup() -> None:
    assert component_type_spec("back_buffer_copy").cls is BackBufferCopyComponent
    assert component_type_spec("screen_texture").cls is ScreenTextureComponent


def test_screen_components_register_for_dict_loading_and_editor_listing() -> None:
    back_buffer_copy = component_from_dict({"type": "back_buffer_copy"})
    screen_texture = component_from_dict({"type": "screen_texture"})

    assert isinstance(back_buffer_copy, BackBufferCopyComponent)
    assert isinstance(screen_texture, ScreenTextureComponent)
    registered = dict(registered_component_types())
    assert registered["back_buffer_copy"] is BackBufferCopyComponent
    assert registered["screen_texture"] is ScreenTextureComponent


def test_screen_component_metadata_has_exact_fields_enums_and_bounds() -> None:
    back_fields = component_type_spec("back_buffer_copy").fields
    screen_fields = component_type_spec("screen_texture").fields

    assert tuple(field.name for field in back_fields) == (
        "copy_mode",
        "rect",
        "capture_id",
        "layer",
        "phase",
        "enabled",
    )
    assert tuple(field.name for field in screen_fields) == (
        "capture_id",
        "uv_rect",
        "width",
        "height",
        "filter",
        "lod",
        "tint",
        "opacity",
        "layer",
        "phase",
        "visible",
        "enabled",
    )

    back = {field.name: field for field in back_fields}
    screen = {field.name: field for field in screen_fields}
    assert back["copy_mode"].enum_values == ("disabled", "rect", "viewport")
    assert back["phase"].enum_values == ("opaque", "transparent", "overlay")
    assert back["rect"].default == (-100.0, -100.0, 200.0, 200.0)
    assert back["rect"].tuple_length == 4
    assert screen["filter"].enum_values == (
        "nearest",
        "linear",
        "nearest_mipmap",
        "linear_mipmap",
    )
    assert screen["phase"].enum_values == ("opaque", "transparent", "overlay")
    assert screen["uv_rect"].default == (0.0, 0.0, 1.0, 1.0)
    assert screen["uv_rect"].tuple_length == 4
    for name in ("width", "height", "lod"):
        assert screen[name].minimum == 0.0
        assert screen[name].maximum is None
    assert screen["opacity"].minimum == 0.0
    assert screen["opacity"].maximum == 1.0


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "back_buffer_copy", "copy_mode": "invalid"},
        {"type": "back_buffer_copy", "phase": "invalid"},
        {"type": "screen_texture", "filter": "invalid"},
        {"type": "screen_texture", "phase": "invalid"},
    ],
)
def test_screen_components_reject_malformed_enum_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        component_from_dict(payload)


@pytest.mark.parametrize("component_type", ["back_buffer_copy", "screen_texture"])
def test_screen_components_reject_empty_capture_ids(component_type: str) -> None:
    with pytest.raises(ValueError):
        component_from_dict({"type": component_type, "capture_id": ""})


def test_screen_components_preserve_disabled_state_through_registry_loading() -> None:
    back_buffer_copy = component_from_dict(
        {"type": "back_buffer_copy", "capture_id": "portal", "enabled": False}
    )
    screen_texture = component_from_dict(
        {"type": "screen_texture", "capture_id": "portal", "enabled": False}
    )

    assert back_buffer_copy.enabled is False
    assert screen_texture.enabled is False
    assert back_buffer_copy.to_dict()["enabled"] is False
    assert screen_texture.to_dict()["enabled"] is False


def test_screen_components_survive_full_scene_json_round_trip() -> None:
    scene = Scene("effects", scene_id="scene-1")
    entity = scene.create_entity("portal", entity_id="entity-1")
    entity.add_component(BackBufferCopyComponent(copy_mode="viewport", capture_id="portal"))
    entity.add_component(ScreenTextureComponent(capture_id="portal", filter="linear_mipmap"))

    restored = Scene.from_dict(json.loads(json.dumps(scene.to_dict())))

    assert restored.to_dict() == scene.to_dict()
    restored_entity = restored.find_entity("entity-1")
    assert restored_entity is not None
    assert isinstance(restored_entity.components[0], BackBufferCopyComponent)
    assert isinstance(restored_entity.components[1], ScreenTextureComponent)
