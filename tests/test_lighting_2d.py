from __future__ import annotations

import math

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.runtime.canvas_effects import CanvasModulateComponent, resolve_canvas_modulation
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Color, LightDescriptor, RenderFrame
from expra_engine.ui.viewport_render_target import build_editor_render_target


def _light_payload(**overrides: object) -> dict[str, object]:
    return {
        "type": "light_2d",
        "enabled": True,
        "visible": True,
        "kind": "point",
        "color": [1.0, 0.7, 0.4, 1.0],
        "energy": 1.0,
        "radius": 2.0,
        "falloff": 2.0,
        "cone_angle": 60.0,
        "height": 1.0,
        **overrides,
    }


def test_light_component_round_trips_through_the_canonical_registry() -> None:
    component = component_from_dict(_light_payload())

    assert component.to_dict() == _light_payload()
    assert tuple(field.name for field in component_type_spec("light_2d").fields) == (
        "kind",
        "color",
        "energy",
        "radius",
        "falloff",
        "cone_angle",
        "height",
        "visible",
        "enabled",
    )
    assert component_type_spec("light_2d").fields[0].enum_values == ("point", "spot")


def test_extractor_emits_parent_composed_world_space_lights() -> None:
    scene = Scene("lights")
    parent = scene.create_entity("actor", entity_id="actor")
    parent.add_component(
        TransformComponent(x=3.0, y=4.0, rotation=90.0, scale_x=2.0, scale_y=2.0)
    )
    child = scene.create_entity("torch", entity_id="torch", parent_id="actor")
    child.add_component(TransformComponent(x=1.0))
    child.add_component(component_from_dict(_light_payload()))

    frame = extract_render_frame(scene)

    assert len(frame.lights) == 1
    light = frame.lights[0]
    assert light.entity_id == "torch"
    assert light.position == (3.0, 6.0, 0.0)
    assert light.direction_degrees == 90.0
    assert light.radius == 4.0
    assert light.color == Color(1.0, 0.7, 0.4, 1.0)
    assert light.height == 1.0


@pytest.mark.parametrize("height", [-0.1, 1024.1, math.nan, math.inf, True])
def test_light_component_rejects_invalid_normal_map_height(height: object) -> None:
    with pytest.raises(ValueError, match="height"):
        component_from_dict(_light_payload(height=height))


def test_light_height_is_separate_from_entity_z_and_only_affects_normal_lighting() -> None:
    scene = Scene("normal light height")
    entity = scene.create_entity("light")
    entity.add_component(TransformComponent(x=4.0))
    entity.add_component(component_from_dict(_light_payload(height=5.0)))

    descriptor = extract_render_frame(scene).lights[0]

    assert descriptor.position == (4.0, 0.0, 0.0)
    assert descriptor.height == 5.0


def test_disabled_or_invisible_lights_are_not_extracted() -> None:
    scene = Scene("inactive lights")
    disabled = scene.create_entity("disabled", enabled=False)
    disabled.add_component(component_from_dict(_light_payload()))
    hidden = scene.create_entity("hidden")
    hidden.add_component(component_from_dict(_light_payload(visible=False)))
    inactive = scene.create_entity("inactive")
    inactive.add_component(component_from_dict(_light_payload(enabled=False)))

    assert extract_render_frame(scene).lights == ()


def test_world_environment_uses_the_explicit_camera_context_level() -> None:
    scene = Scene("overlapping World Levels")
    loaded_first = scene.create_entity("loaded first", entity_id="loaded-first")
    loaded_first.add_component(CanvasModulateComponent((0.2, 0.1, 0.1, 1.0)))
    camera_level = scene.create_entity("camera Level", entity_id="camera-level")
    camera_level.add_component(CanvasModulateComponent((0.1, 0.2, 0.4, 1.0)))

    modulation = resolve_canvas_modulation(scene, entity_ids=("camera-level",))

    assert modulation.source_entity_id == "camera-level"
    assert modulation.color == Color(0.1, 0.2, 0.4, 1.0)

    frame = extract_render_frame(scene, modulation_entity_ids=("camera-level",))
    assert frame.modulation == Color(0.1, 0.2, 0.4, 1.0)


def test_camera_and_editor_preview_can_disable_lighting_without_mutating_scene() -> None:
    scene = Scene("preview control")
    entity = scene.create_entity("light")
    entity.add_component(component_from_dict(_light_payload()))
    scene.camera["lighting_enabled"] = False

    runtime_frame = extract_render_frame(scene)
    preview_target = build_editor_render_target(scene, preview_lighting=False)
    bright_preview_target = build_editor_render_target(scene, preview_lighting=True)

    assert runtime_frame.lighting_enabled is False
    assert preview_target.frame.lighting_enabled is False
    assert bright_preview_target.frame.lighting_enabled is True
    assert scene.camera["lighting_enabled"] is False

    scene.camera["lighting_enabled"] = True
    bright_target = build_editor_render_target(scene, preview_lighting=False)
    enabled_target = build_editor_render_target(scene)

    assert bright_target.frame.lighting_enabled is False
    assert enabled_target.frame.lighting_enabled is True
    assert scene.camera["lighting_enabled"] is True


def test_light_descriptor_rejects_string_and_bool_numeric_fields() -> None:
    values = ("light", "point", (0.0, 0.0, 0.0), Color(1.0, 1.0, 1.0))

    with pytest.raises(ValueError, match="energy must be a finite number"):
        LightDescriptor(*values, energy="1.0", radius=2.0, falloff=2.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="radius must be a finite number"):
        LightDescriptor(*values, energy=1.0, radius=True, falloff=2.0)  # type: ignore[arg-type]


def test_frames_without_lights_keep_the_legacy_default() -> None:
    frame = RenderFrame()

    assert frame.lights == ()
    assert frame.lighting_enabled is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"kind": "directional"}, "kind must be"),
        ({"energy": True}, "energy must be a finite number"),
        ({"radius": "2.0"}, "radius must be a finite number"),
        ({"energy": math.nan}, "energy must be finite"),
        ({"radius": 0.0}, "radius must be positive"),
        ({"falloff": math.inf}, "falloff must be finite"),
        ({"cone_angle": 361.0}, "cone_angle must be greater than 0"),
        ({"color": [1.0, 0.0]}, "color must contain 3 or 4 values"),
        ({"kind": []}, "kind must be 'point' or 'spot'"),
        ({"color": [True, 0.0, 0.0]}, "color channels must be numeric"),
        ({"color": ["1.0", 0.0, 0.0]}, "color channels must be numeric"),
        ({"visible": "false"}, "visible must be a bool"),
        ({"enabled": 1}, "enabled must be a bool"),
    ],
)
def test_light_component_rejects_malformed_or_out_of_range_values(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        component_from_dict(_light_payload(**override))
