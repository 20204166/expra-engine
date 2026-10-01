"""One Python/Rust visibility bridge with an exact Python fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from expra_engine.core.camera import Camera2D
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


def test_project_camera_points_falls_back_to_the_camera_reference(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(position=(3.0, -2.0), target_width=16.0, viewport=(800, 600))
    camera.offset = (0.25, -0.75)
    camera.rotation = 0.4
    points = ((-2.0, 3.0), (0.0, 0.0), (9.5, -11.0))
    monkeypatch.setattr(render_math, "_native_module", None)
    monkeypatch.setattr(render_math, "_native_disabled", False)

    actual = render_math.project_camera_points(iter(points), camera, (800, 600))

    assert actual == tuple(camera.translate_to_screen(point) for point in points)


def test_project_camera_points_calls_native_once_for_the_ordered_batch(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(position=(3.0, -2.0), target_width=16.0, viewport=(800, 600))
    calls = []

    def project_points(points, camera_values):
        calls.append((points, camera_values))
        return [100.0, 200.0, 300.0, 400.0]

    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(visible_mask=lambda *_args: [], project_points=project_points),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)

    actual = render_math.project_camera_points(((1.0, 2.0), (-3.0, 4.0)), camera, (800, 600))

    assert len(calls) == 1
    assert calls[0][0] == [1.0, 2.0, -3.0, 4.0]
    assert len(calls[0][1]) == 8
    assert actual == ((100.0, 200.0), (300.0, 400.0))


@pytest.mark.parametrize(
    "points",
    [
        ((1.0,),),
        ((1.0, 2.0, 3.0),),
        ((float("nan"), 0.0),),
        ((0.0, float("inf")),),
        ((True, 0.0),),
        ((10**400, 0.0),),
    ],
)
def test_project_camera_points_rejects_malformed_or_non_finite_points(points) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(viewport=(800, 600))

    with pytest.raises((TypeError, ValueError)):
        render_math.project_camera_points(points, camera, (800, 600))


def test_project_camera_points_empty_batch_needs_no_native_call(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    def unexpected_call(*_args):
        pytest.fail("empty point batches should not cross the native boundary")

    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(visible_mask=lambda *_args: [], project_points=unexpected_call),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)

    assert render_math.project_camera_points((), Camera2D(), (800, 600)) == ()


def test_project_camera_points_validates_viewport_even_for_empty_batch() -> None:
    from expra_engine.runtime import render_math

    with pytest.raises(ValueError, match="viewport dimensions must be positive"):
        render_math.project_camera_points((), Camera2D(), (0, 600))


def test_project_camera_points_bad_native_result_falls_back_and_disables_native(
    monkeypatch, caplog
) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(position=(1.0, -1.0), target_width=12.0, viewport=(800, 600))
    points = ((2.0, 3.0), (-4.0, 5.0))

    def malformed(_points, _camera):
        return [1.0, 2.0]

    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(visible_mask=lambda *_args: [], project_points=malformed),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)
    monkeypatch.setattr(render_math, "_native_projection_disabled", False)
    monkeypatch.setattr(render_math, "_native_failure_reported", False)
    monkeypatch.setattr(render_math, "_native_projection_failure_reported", False)

    actual = render_math.project_camera_points(points, camera, (800, 600))

    assert actual == tuple(camera.translate_to_screen(point) for point in points)
    assert render_math.native_available() is True
    assert render_math.native_projection_available() is False
    assert "using the Python camera-projection reference" in caplog.text


@pytest.mark.parametrize("bad_result", [[1.0], [float("nan"), 0.0], [True, 0.0]])
def test_invalid_native_projection_results_fall_back(bad_result, monkeypatch) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(viewport=(800, 600))
    points = ((1.0, 2.0),)
    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(
            visible_mask=lambda *_args: [True],
            project_points=lambda *_args: bad_result,
        ),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)
    monkeypatch.setattr(render_math, "_native_projection_disabled", False)
    monkeypatch.setattr(render_math, "_native_projection_failure_reported", False)

    assert render_math.project_camera_points(points, camera, (800, 600)) == (
        camera.translate_to_screen(points[0]),
    )
    assert render_math.native_projection_available() is False
    assert render_math.native_available() is True


def test_strict_native_projection_does_not_fall_back(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(viewport=(800, 600))
    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(
            visible_mask=lambda *_args: [True],
            project_points=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("native projection failed")
            ),
        ),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)
    monkeypatch.setattr(render_math, "_native_projection_disabled", False)
    monkeypatch.setattr(
        render_math,
        "_python_project_camera_points",
        lambda *_args: pytest.fail("strict native projection must not fall back"),
    )

    with pytest.raises(RuntimeError, match="native projection failed"):
        render_math.strict_native_project_camera_points(((1.0, 2.0),), camera, (800, 600))


def test_missing_projection_symbol_does_not_disable_visibility_kernel(monkeypatch) -> None:
    from expra_engine.runtime import render_math

    camera = Camera2D(viewport=(800, 600))
    monkeypatch.setattr(
        render_math,
        "_native_module",
        SimpleNamespace(visible_mask=lambda *_args: [True]),
    )
    monkeypatch.setattr(render_math, "_native_disabled", False)
    monkeypatch.setattr(render_math, "_native_projection_disabled", False)

    result = render_math.project_camera_points(((1.0, 2.0),), camera, (800, 600))

    assert result == (camera.translate_to_screen((1.0, 2.0)),)
    assert render_math.native_available() is True
    assert render_math.native_projection_available() is False


@pytest.mark.parametrize("rotation", (0.0, 0.37, -1.2))
def test_native_projection_matches_python_reference_when_available(rotation: float) -> None:
    from expra_engine.runtime import render_math

    if not render_math.native_projection_available():
        pytest.skip("optional projection kernel is not installed")

    camera = Camera2D(position=(2.5, -1.75), target_width=17.0, viewport=(801, 603))
    camera.offset = (-0.5, 0.25)
    camera.rotation = rotation
    points = ((-5.5, 3.25), (0.0, 0.0), (14.0, -12.75))

    actual = render_math.strict_native_project_camera_points(points, camera, (801, 603))
    expected = tuple(camera.translate_to_screen(point) for point in points)

    assert len(actual) == len(expected)
    for actual_point, expected_point in zip(actual, expected, strict=True):
        assert actual_point == pytest.approx(expected_point, abs=1e-10)
