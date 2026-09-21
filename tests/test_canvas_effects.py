"""Tests for renderer-neutral scene-wide canvas modulation."""

from __future__ import annotations

import math

import pytest

from expra_engine.core.scene import Scene
from expra_engine.runtime.canvas_effects import (
    CanvasModulateComponent,
    CanvasModulation,
    modulate_color,
    resolve_canvas_modulation,
)
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Color


def test_component_defaults_to_neutral_white() -> None:
    component = CanvasModulateComponent()

    assert component.enabled is True
    assert component.color == Color(1.0, 1.0, 1.0, 1.0)


def test_component_serialization_round_trip_preserves_rgba_and_enabled() -> None:
    component = CanvasModulateComponent((0.2, 0.4, 0.6, 0.8), enabled=False)

    restored = CanvasModulateComponent.from_dict(component.to_dict())

    assert restored.enabled is False
    assert restored.color == Color(0.2, 0.4, 0.6, 0.8)


def test_scene_serialization_round_trip_preserves_component() -> None:
    scene = Scene("night")
    entity = scene.create_entity("world tint")
    entity.add_component(CanvasModulateComponent((0.1, 0.2, 0.3, 0.9)))

    restored = Scene.from_dict(scene.to_dict())
    component = restored.entities[0].get_component(CanvasModulateComponent)

    assert component is not None
    assert component.color == Color(0.1, 0.2, 0.3, 0.9)


def test_three_channel_color_defaults_alpha_to_one() -> None:
    component = CanvasModulateComponent((0.2, 0.3, 0.4))

    assert component.color == Color(0.2, 0.3, 0.4, 1.0)


@pytest.mark.parametrize(
    "value",
    [
        (),
        (1.0,),
        (1.0, 1.0),
        (1.0, 1.0, 1.0, 1.0, 1.0),
    ],
)
def test_invalid_color_lengths_are_rejected(value: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        CanvasModulateComponent(value)


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_non_finite_color_channels_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        CanvasModulateComponent((bad, 1.0, 1.0, 1.0))


def test_no_component_resolves_to_neutral_inactive_modulation() -> None:
    result = resolve_canvas_modulation(Scene("plain"))

    assert result == CanvasModulation()
    assert result.active is False


def test_disabled_entity_is_ignored() -> None:
    scene = Scene("disabled")
    disabled = scene.create_entity("disabled", enabled=False)
    disabled.add_component(CanvasModulateComponent((1.0, 0.0, 0.0, 1.0)))
    active = scene.create_entity("active")
    active.add_component(CanvasModulateComponent((0.0, 0.0, 1.0, 1.0)))

    result = resolve_canvas_modulation(scene)

    assert result.source_entity_id == active.entity_id
    assert result.color == Color(0.0, 0.0, 1.0, 1.0)


def test_disabled_component_is_ignored() -> None:
    scene = Scene("disabled component")
    ignored = scene.create_entity("ignored")
    ignored.add_component(
        CanvasModulateComponent((1.0, 0.0, 0.0, 1.0), enabled=False)
    )
    active = scene.create_entity("active")
    active.add_component(CanvasModulateComponent((0.0, 1.0, 0.0, 1.0)))

    result = resolve_canvas_modulation(scene)

    assert result.source_entity_id == active.entity_id
    assert result.duplicate_count == 0


def test_multiple_modulates_choose_first_deterministically_and_report_duplicates() -> None:
    scene = Scene("duplicates")
    first = scene.create_entity("first")
    second = scene.create_entity("second")
    third = scene.create_entity("third")
    first.add_component(CanvasModulateComponent((1.0, 0.0, 0.0, 1.0)))
    second.add_component(CanvasModulateComponent((0.0, 1.0, 0.0, 1.0)))
    third.add_component(CanvasModulateComponent((0.0, 0.0, 1.0, 1.0)))

    result = resolve_canvas_modulation(scene)

    assert result.source_entity_id == first.entity_id
    assert result.color == Color(1.0, 0.0, 0.0, 1.0)
    assert result.duplicate_count == 2


def test_modulate_color_multiplies_rgba_once() -> None:
    result = modulate_color(
        Color(0.8, 0.5, 0.25, 0.5),
        Color(0.5, 0.4, 0.8, 0.5),
    )

    assert result == Color(0.4, 0.2, 0.2, 0.25)


def test_modulate_color_rejects_non_rendering_colors() -> None:
    with pytest.raises(TypeError):
        modulate_color(Color(1.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))  # type: ignore[arg-type]


def test_render_extractor_exposes_resolved_canvas_modulation() -> None:
    scene = Scene("render")
    entity = scene.create_entity("night")
    entity.add_component(CanvasModulateComponent((0.3, 0.4, 0.5, 0.8)))

    frame = extract_render_frame(scene)

    # Integration seam: the canonical frame should carry this resolved state
    # rather than requiring each backend to scan scene components itself.
    assert frame.modulation == Color(0.3, 0.4, 0.5, 0.8)
