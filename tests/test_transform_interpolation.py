"""Focused tests for fixed-tick transform interpolation."""

from __future__ import annotations

import math

import pytest

from expra_engine.runtime.rendering import Transform
from expra_engine.runtime.transform_interpolation import TransformInterpolator


def transform(
    x: float = 0.0,
    y: float = 0.0,
    *,
    rotation: float = 0.0,
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> Transform:
    return Transform(position=(x, y, 0.0), rotation=rotation, scale=scale)


def capture(
    interpolator: TransformInterpolator,
    key: str,
    value: Transform,
    **kwargs,
) -> None:
    interpolator.begin_tick()
    interpolator.capture(key, value, **kwargs)
    interpolator.end_tick()


def test_first_capture_has_no_artificial_motion() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform(10.0, 4.0))

    assert interpolator.sample_local("player", 0.0) == transform(10.0, 4.0)
    assert interpolator.sample_local("player", 0.5) == transform(10.0, 4.0)


def test_position_and_scale_interpolate_between_fixed_ticks() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform())
    capture(
        interpolator,
        "player",
        transform(10.0, 20.0, scale=(3.0, 5.0, 1.0)),
    )

    sampled = interpolator.sample_local("player", 0.25)
    assert sampled.position == pytest.approx((2.5, 5.0, 0.0))
    assert sampled.scale == pytest.approx((1.5, 2.0, 1.0))


def test_rotation_uses_shortest_arc_across_zero() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform(rotation=350.0))
    capture(interpolator, "player", transform(rotation=10.0))

    sampled = interpolator.sample_local("player", 0.5)
    assert sampled.rotation % 360.0 == pytest.approx(0.0)


def test_multiple_writes_in_one_tick_do_not_advance_previous_twice() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform(0.0, 0.0))

    interpolator.begin_tick()
    interpolator.capture("player", transform(4.0, 0.0))
    interpolator.capture("player", transform(10.0, 0.0))
    interpolator.end_tick()

    assert interpolator.sample_local("player", 0.5).position == pytest.approx(
        (5.0, 0.0, 0.0)
    )


def test_parent_and_child_are_interpolated_before_world_composition() -> None:
    interpolator = TransformInterpolator()

    interpolator.begin_tick()
    interpolator.capture("parent", transform(0.0, 0.0))
    interpolator.capture("child", transform(2.0, 0.0), parent="parent")
    interpolator.end_tick()

    interpolator.begin_tick()
    interpolator.capture("parent", transform(10.0, 0.0))
    interpolator.capture("child", transform(4.0, 0.0), parent="parent")
    interpolator.end_tick()

    assert interpolator.sample_world("child", 0.5).position == pytest.approx(
        (8.0, 0.0, 0.0)
    )


def test_parent_rotation_affects_sampled_child_world_position() -> None:
    interpolator = TransformInterpolator()

    interpolator.begin_tick()
    interpolator.capture("parent", transform(rotation=0.0))
    interpolator.capture("child", transform(2.0, 0.0), parent="parent")
    interpolator.end_tick()

    interpolator.begin_tick()
    interpolator.capture("parent", transform(rotation=90.0))
    interpolator.capture("child", transform(2.0, 0.0), parent="parent")
    interpolator.end_tick()

    sampled = interpolator.sample_world("child", 1.0)
    assert sampled.position == pytest.approx((0.0, 2.0, 0.0), abs=1e-9)


def test_missing_parent_is_treated_as_root_like_current_scene_rendering() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "child", transform(3.0, 4.0), parent="missing")

    assert interpolator.sample_world("child", 0.5).position == (3.0, 4.0, 0.0)


def test_request_reset_prevents_teleport_streaking() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform())
    interpolator.request_reset("player")
    capture(interpolator, "player", transform(100.0, 50.0))

    assert interpolator.sample_local("player", 0.01) == transform(100.0, 50.0)


def test_immediate_reset_can_supply_new_transform() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform())
    interpolator.reset("player", transform(8.0, 9.0))

    assert interpolator.sample_local("player", 0.0) == transform(8.0, 9.0)
    assert interpolator.sample_local("player", 1.0) == transform(8.0, 9.0)


def test_non_interpolated_transform_snaps_to_current_tick() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "ui", transform(), interpolated=False)
    capture(interpolator, "ui", transform(10.0, 0.0), interpolated=False)

    assert interpolator.sample_local("ui", 0.0).position == (10.0, 0.0, 0.0)


def test_prune_removes_objects_missing_from_complete_tick_capture() -> None:
    interpolator = TransformInterpolator()

    interpolator.begin_tick()
    interpolator.capture("a", transform())
    interpolator.capture("b", transform())
    interpolator.end_tick()

    interpolator.begin_tick()
    interpolator.capture("a", transform(1.0, 0.0))
    interpolator.end_tick(prune=True)

    assert interpolator.tracked == ("a",)
    assert "b" not in interpolator


def test_remove_and_clear_are_idempotent_for_runtime_teardown() -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform())

    assert interpolator.remove("player") is True
    assert interpolator.remove("player") is False

    capture(interpolator, "enemy", transform())
    interpolator.clear()
    assert interpolator.tracked == ()
    assert interpolator.active is False


@pytest.mark.parametrize("fraction", [-0.01, 1.01, math.inf, -math.inf, math.nan])
def test_invalid_interpolation_fraction_is_rejected(fraction: float) -> None:
    interpolator = TransformInterpolator()
    capture(interpolator, "player", transform())

    with pytest.raises(ValueError):
        interpolator.sample_local("player", fraction)


def test_capture_requires_explicit_tick_boundary() -> None:
    interpolator = TransformInterpolator()

    with pytest.raises(RuntimeError):
        interpolator.capture("player", transform())

    interpolator.begin_tick()
    with pytest.raises(RuntimeError):
        interpolator.begin_tick()
    interpolator.capture("player", transform())
    interpolator.end_tick()

    with pytest.raises(RuntimeError):
        interpolator.end_tick()


def test_self_parent_is_rejected() -> None:
    interpolator = TransformInterpolator()
    interpolator.begin_tick()
    with pytest.raises(ValueError):
        interpolator.capture("player", transform(), parent="player")


def test_cycle_is_detected_when_sampling_world_transform() -> None:
    interpolator = TransformInterpolator()
    interpolator.begin_tick()
    interpolator.capture("a", transform(), parent="b")
    interpolator.capture("b", transform(), parent="a")
    interpolator.end_tick()

    with pytest.raises(ValueError):
        interpolator.sample_world("a", 0.5)


def test_unknown_transform_raises_key_error() -> None:
    interpolator = TransformInterpolator()

    with pytest.raises(KeyError):
        interpolator.sample_local("missing", 0.5)
