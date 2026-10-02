from __future__ import annotations

import pytest

from expra_engine.runtime.rendering import (
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    RenderSpace,
    Transform,
    Viewport,
)


def _sparse_frame(count: int) -> RenderFrame:
    return RenderFrame(
        tuple(
            RenderItem(
                f"item-{index}",
                PrimitiveDescriptor("rectangle", (1.0, 1.0)),
                Transform(position=(float(index % 100) * 4.0, float(index // 100) * 4.0, 0.0)),
            )
            for index in range(count)
        )
    )


def test_camera_visibility_checks_spatial_candidates_not_the_complete_frame(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    frame = _sparse_frame(5000)
    context = RenderContext(Viewport(0, 0, 800, 600), OrthographicCamera(width=20.0, height=15.0))
    ordered = frame.ordered_items()
    reference = tuple(item for item in ordered if item.is_visible(context))
    calls = 0
    original = RenderItem.is_visible

    def counted(item: RenderItem, render_context: RenderContext) -> bool:
        nonlocal calls
        calls += 1
        return original(item, render_context)

    monkeypatch.setattr(render_math, "_native_module", None)
    monkeypatch.setattr(RenderItem, "is_visible", counted)

    visible = frame.visible_items(context)

    assert visible == reference
    assert calls < len(ordered) // 4


@pytest.mark.parametrize("rotation", [0.0, 0.37, -1.2])
def test_spatial_visibility_matches_exhaustive_renderitem_visibility(monkeypatch, rotation) -> None:
    from expra_engine.runtime import render_math

    frame = RenderFrame(
        (
            RenderItem(
                "polygon",
                PrimitiveDescriptor(
                    "polygon",
                    (1.0, 1.0),
                    points=((-8.0, -1.0), (1.0, -2.0), (4.0, 7.0)),
                ),
                Transform(position=(11.0, 1.0, 0.0), rotation=23.0),
            ),
            RenderItem(
                "line",
                PrimitiveDescriptor("line", (1.0, 1.0), points=((-5.0, 0.0), (5.0, 0.0)), thickness=2.0),
                Transform(position=(0.0, 9.0, 0.0), rotation=-18.0),
            ),
            RenderItem(
                "circle",
                PrimitiveDescriptor("circle", (2.0, 2.0), radius=1.0),
                Transform(position=(-12.0, 0.0, 0.0), scale=(1.5, 0.5, 1.0)),
            ),
            RenderItem(
                "viewport",
                PrimitiveDescriptor("rectangle", (12.0, 8.0)),
                Transform(position=(500.0, -300.0, 0.0)),
                space=RenderSpace.VIEWPORT,
                viewport_anchor=(0.5, 0.5),
            ),
            RenderItem(
                "far-depth",
                PrimitiveDescriptor("rectangle", (1.0, 1.0)),
                Transform(position=(0.0, 0.0, 5000.0)),
            ),
        )
    )
    camera = OrthographicCamera(position=(1.0, -2.0, 0.0), width=20.0, height=12.0)
    camera.rotation = rotation
    context = RenderContext(Viewport(13, 17, 800, 600), camera)
    ordered = frame.ordered_items()
    expected = tuple(item for item in ordered if item.is_visible(context))

    monkeypatch.setattr(render_math, "_native_module", None)
    actual = frame.visible_items(context)

    assert tuple(item.key for item in actual) == tuple(item.key for item in expected)


def test_spatial_visibility_keeps_thick_lines_visible_across_viewport_aspect_ratios(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    line = RenderItem(
        "wide-screen-line-padding",
        PrimitiveDescriptor("line", (1.0, 1.0), points=((-1.0, 0.0), (1.0, 0.0)), thickness=2.0),
        Transform(position=(0.0, 60.0, 0.0)),
    )
    frame = RenderFrame((line,))
    context = RenderContext(
        Viewport(0, 0, 800, 100),
        OrthographicCamera(width=10.0, height=100.0),
    )
    assert line.is_visible(context)
    monkeypatch.setattr(render_math, "_native_module", None)

    assert tuple(item.key for item in frame.visible_items(context)) == (line.key,)
