"""Tests for ordered render planning and lazy screen capture."""

import pytest

from expra_engine.runtime.render_pipeline import (
    CaptureScreenOp,
    DrawItemOp,
    DrawScreenTextureOp,
    GenerateScreenMipmapsOp,
    RenderOrder,
    RenderPlan,
    RenderPlanBuilder,
)
from expra_engine.runtime.rendering import (
    PrimitiveDescriptor,
    RenderItem,
    RenderPhase,
    Transform,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyMode,
    BackBufferCopyRequest,
    ScreenTextureDrawRequest,
    ScreenTextureFilter,
)


def item(name, *, layer=0, phase=RenderPhase.OPAQUE, z=0.0):
    return RenderItem(
        name,
        PrimitiveDescriptor("point"),
        Transform(position=(0.0, 0.0, z)),
        layer=layer,
        phase=phase,
    )


def screen_request(name="screen", *, filter=ScreenTextureFilter.LINEAR):
    return ScreenTextureDrawRequest(
        "screen-entity",
        name,
        Transform(),
        2.0,
        2.0,
        filter=filter,
    )


def test_plan_preserves_existing_draw_order_contract():
    builder = RenderPlanBuilder()
    builder.add_item(item("later", layer=2), insertion_index=1)
    builder.add_item(item("earlier", layer=1), insertion_index=0)
    plan = builder.build()
    assert [op.item.key for op in plan.operations if isinstance(op, DrawItemOp)] == [
        "earlier",
        "later",
    ]


def test_explicit_capture_is_interleaved_between_draws():
    builder = RenderPlanBuilder()
    builder.add_item(item("before"), insertion_index=0)
    builder.add_capture(
        BackBufferCopyRequest(
            "copy",
            "screen",
            BackBufferCopyMode.VIEWPORT,
            Transform(),
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    builder.add_item(item("after"), insertion_index=2)
    ops = builder.build().operations
    assert isinstance(ops[0], DrawItemOp)
    assert isinstance(ops[1], CaptureScreenOp)
    assert isinstance(ops[2], DrawItemOp)


def test_first_screen_consumer_gets_automatic_full_viewport_capture():
    builder = RenderPlanBuilder()
    builder.add_item(item("background"), insertion_index=0)
    builder.add_screen_texture(
        screen_request(),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    ops = builder.build().operations
    assert isinstance(ops[0], DrawItemOp)
    assert isinstance(ops[1], CaptureScreenOp)
    assert ops[1].automatic is True
    assert ops[1].request.mode is BackBufferCopyMode.VIEWPORT
    assert ops[1].request.capture_id == "screen"
    assert isinstance(ops[2], DrawScreenTextureOp)


def test_explicit_capture_prevents_redundant_automatic_capture():
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("copy", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        screen_request(),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    captures = [
        op for op in builder.build().operations if isinstance(op, CaptureScreenOp)
    ]
    assert len(captures) == 1
    assert not captures[0].automatic


def test_multiple_consumers_reuse_snapshot_until_next_explicit_capture():
    builder = RenderPlanBuilder()
    for index in range(2):
        builder.add_screen_texture(
            ScreenTextureDrawRequest(
                f"screen-{index}",
                "screen",
                Transform(),
                1.0,
                1.0,
            ),
            phase=RenderPhase.OPAQUE,
            layer=0,
            insertion_index=index,
        )
    captures = [
        op for op in builder.build().operations if isinstance(op, CaptureScreenOp)
    ]
    assert len(captures) == 1


def test_explicit_capture_screen_consumer_and_following_draw_are_ordered():
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("copy", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        screen_request(),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    builder.add_item(item("after"), insertion_index=2)

    operations = builder.build().operations

    assert [type(operation) for operation in operations] == [
        CaptureScreenOp,
        DrawScreenTextureOp,
        DrawItemOp,
    ]


def test_mipmap_consumer_generates_mipmaps_lazily_once():
    builder = RenderPlanBuilder()
    builder.add_screen_texture(
        screen_request(filter=ScreenTextureFilter.LINEAR_MIPMAP),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "second",
            "screen",
            Transform(),
            1.0,
            1.0,
            filter=ScreenTextureFilter.NEAREST_MIPMAP,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    plan = builder.build()
    assert len(
        [op for op in plan.operations if isinstance(op, GenerateScreenMipmapsOp)]
    ) == 1
    assert plan.requirements.screen_texture_mipmaps


def test_non_mipmap_consumer_does_not_consume_mipmap_state():
    builder = RenderPlanBuilder()
    builder.add_screen_texture(
        screen_request(),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        screen_request(filter=ScreenTextureFilter.LINEAR_MIPMAP),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )

    plan = builder.build()

    assert len(
        [op for op in plan.operations if isinstance(op, GenerateScreenMipmapsOp)]
    ) == 1


def test_new_capture_invalidates_previous_mip_pyramid():
    builder = RenderPlanBuilder()
    builder.add_screen_texture(
        screen_request(filter=ScreenTextureFilter.LINEAR_MIPMAP),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_capture(
        BackBufferCopyRequest("copy", "screen", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "after",
            "screen",
            Transform(),
            1.0,
            1.0,
            filter=ScreenTextureFilter.LINEAR_MIPMAP,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=2,
    )
    assert len(
        [
            op
            for op in builder.build().operations
            if isinstance(op, GenerateScreenMipmapsOp)
        ]
    ) == 2


def test_recapture_resets_mipmap_state_for_the_same_named_slot():
    builder = RenderPlanBuilder()
    builder.add_capture(
        BackBufferCopyRequest("first", "portal", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "consumer-1",
            "portal",
            Transform(),
            1.0,
            1.0,
            filter=ScreenTextureFilter.LINEAR_MIPMAP,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    builder.add_capture(
        BackBufferCopyRequest("second", "portal", BackBufferCopyMode.VIEWPORT),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=2,
    )
    builder.add_screen_texture(
        ScreenTextureDrawRequest(
            "consumer-2",
            "portal",
            Transform(),
            1.0,
            1.0,
            filter=ScreenTextureFilter.LINEAR_MIPMAP,
        ),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=3,
    )

    operations = builder.build().operations
    mipmaps = [
        operation
        for operation in operations
        if isinstance(operation, GenerateScreenMipmapsOp)
    ]

    assert len(mipmaps) == 2
    assert [operation.capture_id for operation in mipmaps] == ["portal", "portal"]


def test_named_capture_slots_are_independent():
    builder = RenderPlanBuilder()
    builder.add_screen_texture(
        screen_request("left"),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=0,
    )
    builder.add_screen_texture(
        screen_request("right"),
        phase=RenderPhase.OPAQUE,
        layer=0,
        insertion_index=1,
    )
    captures = [
        op.request.capture_id
        for op in builder.build().operations
        if isinstance(op, CaptureScreenOp)
    ]
    assert captures == ["left", "right"]


def test_render_plan_rejects_out_of_order_manual_operations():
    low = RenderOrder(RenderPhase.OPAQUE.value, 0, 0.0, 0)
    high = RenderOrder(RenderPhase.OVERLAY.value, 0, 0.0, 1)
    with pytest.raises(ValueError):
        RenderPlan(
            (
                DrawItemOp(high, item("high", phase=RenderPhase.OVERLAY)),
                DrawItemOp(low, item("low")),
            )
        )
