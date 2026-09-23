"""Tests for renderer-neutral BackBufferCopy and screen-texture scene data."""

import json
import math
from dataclasses import FrozenInstanceError

import pytest

from expra_engine.runtime.rendering import Color, RenderPhase, Transform
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureComponent,
    ScreenTextureDrawRequest,
    ScreenTextureFilter,
    ScreenTextureUsage,
)
from expra_engine.ui_model.geometry import Rect


def test_back_buffer_defaults_preserve_source_rect_and_named_slot():
    component = BackBufferCopyComponent()
    assert component.copy_mode is BackBufferCopyMode.RECT
    assert component.rect == Rect(-100.0, -100.0, 200.0, 200.0)
    assert component.capture_id == "screen"
    assert component.phase is RenderPhase.OPAQUE


def test_back_buffer_round_trip_is_json_safe():
    component = BackBufferCopyComponent(
        copy_mode="viewport",
        rect=(-4.0, 3.0, 20.0, 30.0),
        capture_id="portal",
        layer=4,
        phase="overlay",
        enabled=False,
    )
    payload = component.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert BackBufferCopyComponent.from_dict(payload).to_dict() == payload


def test_screen_texture_round_trip_preserves_sampling_intent():
    component = ScreenTextureComponent(
        capture_id="portal",
        uv_rect=(0.25, 0.1, 0.5, 0.8),
        width=8,
        height=4,
        filter="linear_mipmap",
        lod=2.0,
        tint=(0.5, 0.6, 0.7, 0.8),
        opacity=0.75,
        layer=3,
        phase="overlay",
        visible=False,
    )
    restored = ScreenTextureComponent.from_dict(component.to_dict())
    assert restored.to_dict() == component.to_dict()
    assert restored.usage == ScreenTextureUsage("portal", True, True)


def test_non_mipmap_filter_does_not_request_mipmaps():
    assert not ScreenTextureComponent(filter="nearest").usage.uses_mipmaps
    assert not ScreenTextureComponent(filter="linear").usage.uses_mipmaps


@pytest.mark.parametrize(
    "filter_name",
    ["nearest_mipmap", "linear_mipmap"],
)
def test_mipmap_filters_request_mipmaps(filter_name):
    assert ScreenTextureComponent(filter=filter_name).usage.uses_mipmaps


def test_usage_rejects_mipmaps_without_screen_texture():
    with pytest.raises(ValueError):
        ScreenTextureUsage(uses_screen_texture=False, uses_mipmaps=True)


@pytest.mark.parametrize(
    "uv",
    [
        (-0.1, 0.0, 1.0, 1.0),
        (0.0, -0.1, 1.0, 1.0),
        (0.5, 0.0, 0.6, 1.0),
        (0.0, 0.5, 1.0, 0.6),
    ],
)
def test_uv_rect_must_remain_normalized(uv):
    with pytest.raises(ValueError):
        ScreenTextureComponent(uv_rect=uv)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_screen_texture_values_are_rejected(bad):
    with pytest.raises(ValueError):
        ScreenTextureComponent(width=bad)
    with pytest.raises(ValueError):
        ScreenTextureComponent(lod=bad)


def test_opacity_and_dimensions_validate():
    with pytest.raises(ValueError):
        ScreenTextureComponent(width=0)
    with pytest.raises(ValueError):
        ScreenTextureComponent(height=-1)
    with pytest.raises(ValueError):
        ScreenTextureComponent(opacity=1.01)


def test_capture_request_rejects_disabled_mode():
    with pytest.raises(ValueError):
        BackBufferCopyRequest(
            "capture",
            "screen",
            BackBufferCopyMode.DISABLED,
        )


def test_capture_request_rejects_unsupported_mode():
    with pytest.raises(ValueError):
        BackBufferCopyRequest(
            "capture",
            "screen",
            "unsupported",  # type: ignore[arg-type]
            Transform(),
            Rect(0.0, 0.0, 1.0, 1.0),
        )


def test_screen_texture_constructors_reject_empty_capture_ids():
    with pytest.raises(ValueError):
        BackBufferCopyComponent(capture_id="")
    with pytest.raises(ValueError):
        ScreenTextureComponent(capture_id=" ")
    with pytest.raises(ValueError):
        BackBufferCopyRequest(
            "capture",
            "",
            BackBufferCopyMode.VIEWPORT,
            Transform(),
            Rect(0.0, 0.0, 1.0, 1.0),
        )


@pytest.mark.parametrize("field", ["enabled", "visible"])
def test_screen_texture_deserialization_rejects_non_boolean_flags(field):
    payload = {
        "type": "screen_texture",
        "capture_id": "screen",
        field: "false",
    }
    with pytest.raises(ValueError, match=field):
        ScreenTextureComponent.from_dict(payload)


def test_back_buffer_deserialization_rejects_null_capture_id():
    with pytest.raises(ValueError, match="capture_id"):
        BackBufferCopyComponent.from_dict(
            {"type": "back_buffer_copy", "capture_id": None}
        )


def test_render_effect_is_frozen_and_renderer_neutral():
    request = BackBufferCopyRequest(
        "capture",
        "screen",
        BackBufferCopyMode.VIEWPORT,
        Transform(),
        Rect(0.0, 0.0, 1.0, 1.0),
    )
    effect = RenderEffect(request, RenderPhase.OPAQUE, 3)

    assert effect.request is request
    assert effect.phase is RenderPhase.OPAQUE
    assert effect.layer == 3
    assert "pygame" not in RenderEffect.__module__
    with pytest.raises(FrozenInstanceError):
        effect.layer = 4  # type: ignore[misc]


def test_screen_draw_request_reports_usage_and_is_backend_neutral():
    request = ScreenTextureDrawRequest(
        "mirror",
        "screen",
        Transform(position=(2.0, 3.0, 0.0)),
        4.0,
        5.0,
        filter=ScreenTextureFilter.LINEAR_MIPMAP,
        lod=1.0,
        tint=Color(0.5, 0.5, 0.5, 1.0),
    )
    assert request.usage.uses_screen_texture
    assert request.usage.uses_mipmaps
    assert "pygame" not in request.__class__.__module__
