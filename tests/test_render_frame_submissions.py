"""Tests for the additive RenderFrame submission stream and planner adapter."""

import pytest

from expra_engine.runtime.render_pipeline import (
    CaptureScreenOp,
    DrawItemOp,
    DrawScreenTextureOp,
    RenderPlanBuilder,
)
from expra_engine.runtime.rendering import (
    Color,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderFrame,
    RenderItem,
    RenderPhase,
    Transform,
    Viewport,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureDrawRequest,
)


def _item(
    key: str,
    *,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    phase: RenderPhase = RenderPhase.OPAQUE,
    layer: int = 0,
) -> RenderItem:
    return RenderItem(
        key,
        PrimitiveDescriptor("point"),
        Transform(position=position),
        phase=phase,
        layer=layer,
    )


def _capture(
    entity_id: str = "capture",
    capture_id: str = "screen",
    *,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> RenderEffect:
    return RenderEffect(
        BackBufferCopyRequest(
            entity_id,
            capture_id,
            BackBufferCopyMode.VIEWPORT,
            Transform(position=position),
        ),
        RenderPhase.OPAQUE,
        0,
    )


def _screen(
    entity_id: str = "consumer",
    capture_id: str = "screen",
    *,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> RenderEffect:
    return RenderEffect(
        ScreenTextureDrawRequest(
            entity_id,
            capture_id,
            Transform(position=position),
            2.0,
            2.0,
        ),
        RenderPhase.OPAQUE,
        0,
    )


def test_render_frame_defaults_and_preserves_old_positional_construction() -> None:
    assert RenderFrame().items == ()
    assert RenderFrame().submissions == ()

    item = _item("draw")
    payload = object()
    modulation = Color(0.5, 0.6, 0.7, 0.8)
    frame = RenderFrame((item,), 0.25, payload, modulation)

    assert frame.items == (item,)
    assert frame.elapsed == 0.25
    assert frame.payload is payload
    assert frame.modulation is modulation
    assert frame.submissions == ()


def test_render_frame_normalizes_submissions_to_a_tuple() -> None:
    item = _item("draw")
    frame = RenderFrame(submissions=[item])

    assert frame.submissions == (item,)
    assert isinstance(frame.submissions, tuple)


def test_plan_builder_converts_a_mixed_submission_stream() -> None:
    item = _item("draw")
    frame = RenderFrame(
        items=(item,),
        submissions=(item, _capture()),
    )

    plan = RenderPlanBuilder.from_frame(frame)

    assert [type(operation) for operation in plan.operations] == [
        DrawItemOp,
        CaptureScreenOp,
    ]


def test_plan_builder_falls_back_to_items_for_an_old_frame() -> None:
    plan = RenderPlanBuilder.from_frame(RenderFrame(items=(_item("draw"),)))

    assert [operation.item.key for operation in plan.operations if isinstance(operation, DrawItemOp)] == [
        "draw"
    ]


def test_plan_builder_preserves_equal_order_submission_order() -> None:
    first = _item("first")
    capture = _capture()
    last = _item("last")
    frame = RenderFrame(submissions=(first, capture, last))

    operations = RenderPlanBuilder.from_frame(frame).operations

    assert [type(operation) for operation in operations] == [
        DrawItemOp,
        CaptureScreenOp,
        DrawItemOp,
    ]
    assert [
        operation.item.key
        for operation in operations
        if isinstance(operation, DrawItemOp)
    ] == ["first", "last"]
    assert all(
        earlier.order <= later.order
        for earlier, later in zip(operations, operations[1:])
    )


def test_plan_builder_filters_only_invisible_ordinary_items() -> None:
    context = RenderContext(
        Viewport(0, 0, 100, 100),
        OrthographicCamera(width=10.0, height=10.0),
    )
    outside = _item("outside", position=(100.0, 100.0, 0.0))
    capture = _capture(position=(100.0, 100.0, 0.0))
    frame = RenderFrame(submissions=(outside, capture))

    plan = RenderPlanBuilder.from_frame(frame, context)

    assert not any(isinstance(operation, DrawItemOp) for operation in plan.operations)
    assert any(isinstance(operation, CaptureScreenOp) for operation in plan.operations)


def test_plan_builder_rejects_unsupported_submission_types() -> None:
    with pytest.raises(TypeError, match="unsupported submission"):
        RenderPlanBuilder.from_frame(RenderFrame(submissions=(object(),)))


def test_plan_builder_mixed_conversion_stays_backend_neutral() -> None:
    frame = RenderFrame(submissions=(_screen(),))

    plan = RenderPlanBuilder.from_frame(frame)

    assert isinstance(plan.operations[-1], DrawScreenTextureOp)
    assert "pygame" not in RenderPlanBuilder.__module__
