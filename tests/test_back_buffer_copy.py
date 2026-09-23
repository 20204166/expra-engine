"""Focused tests for BackBufferCopy's renderer-neutral contract."""

import math

import pytest

from expra_engine.core.scene import Scene
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Transform, Viewport
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
)
from expra_engine.ui_model.geometry import Rect


def test_defaults_match_source_contract():
    component = BackBufferCopyComponent()
    assert component.copy_mode is BackBufferCopyMode.RECT
    assert component.rect == Rect(-100.0, -100.0, 200.0, 200.0)


def test_serialization_round_trip():
    component = BackBufferCopyComponent(
        copy_mode=BackBufferCopyMode.VIEWPORT,
        rect=(-4.0, 3.0, 20.0, 30.0),
        enabled=False,
    )
    restored = BackBufferCopyComponent.from_dict(component.to_dict())
    assert restored.to_dict() == component.to_dict()


def test_disabled_component_emits_no_effect_marker():
    scene = Scene("effects")
    entity = scene.create_entity("capture", entity_id="capture")
    entity.add_component(BackBufferCopyComponent(enabled=False))

    frame = extract_render_frame(scene)

    assert not any(
        isinstance(entry, RenderEffect) for entry in getattr(frame, "submissions", ())
    )


def test_disabled_mode_request_is_rejected():
    with pytest.raises(ValueError):
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.DISABLED,
            Transform(),
            Rect(0.0, 0.0, 10.0, 10.0),
        )


def test_invalid_copy_mode_is_rejected():
    with pytest.raises(ValueError):
        BackBufferCopyComponent(copy_mode="unknown")


def test_rect_mode_preserves_unclamped_configured_rect():
    transform = Transform(position=(4.0, 5.0, 2.0), rotation=15.0, scale=(2.0, 3.0, 1.0))
    request = BackBufferCopyRequest(
        "capture",
        "portal",
        BackBufferCopyMode.RECT,
        transform,
        Rect(-50.0, -20.0, 200.0, 150.0),
    )
    assert request.entity_id == "capture"
    assert request.capture_id == "portal"
    assert request.mode is BackBufferCopyMode.RECT
    assert request.transform == transform
    assert request.rect == Rect(-50.0, -20.0, 200.0, 150.0)


def test_zero_size_rect_is_preserved_for_backend_policy():
    request = BackBufferCopyRequest(
        "capture",
        "screen",
        BackBufferCopyMode.RECT,
        Transform(),
        Rect(4.0, 5.0, 0.0, 0.0),
    )
    assert request.rect == Rect(4.0, 5.0, 0.0, 0.0)


def test_viewport_mode_resolves_exact_viewport_rectangle():
    viewport = Viewport(10, 20, 320, 240)
    request = BackBufferCopyRequest(
        "capture",
        "screen",
        BackBufferCopyMode.VIEWPORT,
        Transform(),
        Rect(viewport.x, viewport.y, viewport.width, viewport.height),
    )
    assert request.rect == Rect(10.0, 20.0, 320.0, 240.0)


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_non_finite_rect_values_are_rejected(bad):
    with pytest.raises(ValueError):
        BackBufferCopyComponent(rect=(0.0, 0.0, bad, 10.0))


def test_negative_rect_dimensions_are_rejected():
    with pytest.raises(ValueError):
        BackBufferCopyComponent(rect=(0.0, 0.0, -1.0, 10.0))
