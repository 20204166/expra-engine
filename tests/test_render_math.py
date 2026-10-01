"""One Python/Rust visibility bridge with an exact Python fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from expra_engine.runtime.rendering import (
    MaterialDescriptor,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    RenderSpace,
    Transform,
    Viewport,
)


def _frame() -> RenderFrame:
    return RenderFrame(
        (
            RenderItem("visible", PrimitiveDescriptor("rectangle", (2.0, 2.0)), Transform()),
            RenderItem(
                "outside",
                PrimitiveDescriptor("rectangle", (2.0, 2.0)),
                Transform(position=(1000.0, 0.0, 0.0)),
            ),
        )
    )


def test_render_frame_visibility_uses_the_single_python_fallback(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    monkeypatch.setattr(render_math, "_native_module", None)
    frame = _frame()
    context = RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera())

    visible = frame.visible_items(context)

    assert tuple(item.key for item in visible) == tuple(
        item.key for item in frame.ordered_items() if item.is_visible(context)
    )
    assert tuple(item.key for item in visible) == ("visible",)


def test_render_frame_visibility_calls_native_once_for_the_whole_batch(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    calls = []

    def visible_mask(records, points, camera, viewport):
        calls.append((records, points, camera, viewport))
        return [True, False]

    monkeypatch.setattr(render_math, "_native_module", SimpleNamespace(visible_mask=visible_mask))
    frame = _frame()
    context = RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera())

    visible = frame.visible_items(context)

    assert len(calls) == 1
    assert tuple(item.key for item in visible) == ("visible",)
    assert len(calls[0][0]) == 21 * len(frame.items)


def test_broken_optional_native_bridge_falls_back_to_python(monkeypatch, caplog) -> None:
    from expra_engine.runtime import render_math

    def broken(*_args):
        raise RuntimeError("native kernel unavailable")

    monkeypatch.setattr(render_math, "_native_module", SimpleNamespace(visible_mask=broken))
    monkeypatch.setattr(render_math, "_native_disabled", False)
    frame = _frame()
    context = RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera())

    visible = frame.visible_items(context)

    assert tuple(item.key for item in visible) == ("visible",)
    assert render_math._native_disabled is True
    assert "using the Python visibility reference" in caplog.text


def test_strict_native_mode_does_not_fall_back(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    def broken(*_args):
        raise RuntimeError("native kernel unavailable")

    monkeypatch.setattr(render_math, "_native_module", SimpleNamespace(visible_mask=broken))
    monkeypatch.setattr(render_math, "_native_disabled", False)
    monkeypatch.setattr(
        render_math,
        "python_visible_mask",
        lambda *_args: pytest.fail("strict native mode must not invoke Python fallback"),
    )
    frame = _frame()
    context = RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera())

    with pytest.raises(RuntimeError, match="native kernel unavailable"):
        render_math.strict_native_visible_mask(frame.ordered_items(), context)


def test_native_visibility_matches_reference_for_supported_primitive_kinds() -> None:
    from expra_engine.runtime import render_math

    if not render_math.native_available():
        pytest.skip("optional expra_render_math extension is not installed")

    camera = OrthographicCamera(position=(1.5, -0.75, 0.0), width=18.0, height=10.0)
    camera.offset = (0.25, -0.5)
    camera.rotation = 0.31
    context = RenderContext(Viewport(13, 17, 240, 140), camera)
    items = (
        RenderItem("point", PrimitiveDescriptor("point", (1.0, 1.0), radius=0.8), Transform(position=(-1.0, 0.5, 0.0))),
        RenderItem("circle", PrimitiveDescriptor("circle", (3.0, 2.0), radius=1.2), Transform(position=(4.0, -1.0, 0.0), scale=(1.2, 0.7, 1.0))),
        RenderItem("rect", PrimitiveDescriptor("rect", (2.0, 3.0)), Transform(position=(0.0, 1.0, 0.0), rotation=27.0)),
        RenderItem("rectangle", PrimitiveDescriptor("rectangle", (2.5, 1.5)), Transform(position=(8.5, 0.0, 0.0))),
        RenderItem("rounded", PrimitiveDescriptor("rounded_rectangle", (3.0, 1.0), radius=0.2), Transform(position=(-8.0, -3.0, 0.0), rotation=-12.0)),
        RenderItem(
            "polygon",
            PrimitiveDescriptor("polygon", (1.0, 1.0), points=((-1.0, -1.0), (1.5, -0.5), (0.0, 1.5))),
            Transform(position=(2.0, 2.0, 0.0), scale=(1.4, 0.8, 1.0), rotation=19.0),
            material=MaterialDescriptor(outline_width=1.7),
        ),
        RenderItem("line", PrimitiveDescriptor("line", (1.0, 1.0), points=((-2.0, 0.0), (2.0, 1.0)), thickness=0.35), Transform(position=(0.0, -3.5, 0.0), rotation=-8.0)),
        RenderItem(
            "viewport",
            PrimitiveDescriptor("rectangle", (8.0, 5.0)),
            Transform(position=(3.0, -2.0, 0.0), rotation=13.0),
            space=RenderSpace.VIEWPORT,
            viewport_anchor=(0.25, 0.75),
            viewport_offset=(7.0, -5.0),
        ),
        RenderItem("hidden", PrimitiveDescriptor("circle", (1.0, 1.0), radius=2.0), Transform(), visible=False),
        RenderItem("depth", PrimitiveDescriptor("rectangle", (1.0, 1.0)), Transform(position=(0.0, 0.0, 1500.0))),
        RenderItem("fallback-kind", PrimitiveDescriptor("sprite", (3.0, 1.0)), Transform(position=(1.0, -1.0, 0.0))),
    )

    native_mask = render_math.strict_native_visible_mask(items, context)

    assert native_mask == render_math.python_visible_mask(items, context)
