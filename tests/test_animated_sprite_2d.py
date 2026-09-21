"""Focused tests for the AnimatedSprite2D conversion."""

import math

import pytest

from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
    SpriteLoopMode,
)
from expra_engine.runtime.animation import SpriteRegion


def frames(loop=SpriteLoopMode.LINEAR):
    return SpriteFrames2D(
        {
            "walk": SpriteAnimation2D(
                (
                    SpriteFrame2D("hero.png", region=SpriteRegion(0, 0, 16, 16)),
                    SpriteFrame2D("hero.png", duration=2.0, region=SpriteRegion(16, 0, 16, 16)),
                ),
                speed_fps=10.0,
                loop_mode=loop,
            )
        }
    )


def test_component_round_trip_preserves_full_configuration():
    component = AnimatedSprite2DComponent(
        frames(),
        animation="walk",
        autoplay="walk",
        frame=1,
        frame_progress=0.5,
        speed_scale=2.0,
        centered=False,
        offset=(2.0, -3.0),
        flip_h=True,
        flip_v=True,
        layer=4,
        visible=False,
    )
    restored = AnimatedSprite2DComponent.from_dict(component.to_dict())
    assert restored.to_dict() == component.to_dict()


def test_autoplay_and_per_frame_duration():
    player = AnimatedSpritePlayer2D(
        AnimatedSprite2DComponent(frames(), animation="walk", autoplay="walk")
    )
    player.start()
    player.advance(0.1)
    assert player.frame == 1
    assert player.frame_progress == pytest.approx(0.0)
    player.advance(0.1)
    assert player.frame == 1
    assert player.frame_progress == pytest.approx(0.5)


def test_non_looping_finishes_and_pauses_at_last_frame():
    player = AnimatedSpritePlayer2D(
        AnimatedSprite2DComponent(frames(SpriteLoopMode.NONE), animation="walk")
    )
    player.play("walk")
    events = player.advance(1.0)
    assert player.playing is False
    assert player.frame == 1
    assert player.frame_progress == 1.0
    assert any(event.kind == "animation_finished" for event in events)


def test_linear_loop_wraps_and_emits_loop_event():
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    player.play()
    events = player.advance(0.31)
    assert any(event.kind == "animation_looped" for event in events)
    assert player.frame == 0


def test_play_backwards_starts_from_end_and_moves_back():
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    player.play_backwards()
    assert player.frame == 1
    assert player.frame_progress == 1.0
    player.advance(0.2)
    assert player.frame == 0


def test_pingpong_reverses_direction_at_endpoint():
    player = AnimatedSpritePlayer2D(
        AnimatedSprite2DComponent(frames(SpriteLoopMode.PINGPONG), animation="walk")
    )
    player.play()
    player.advance(0.3)
    assert player.playing_speed < 0.0


def test_set_frame_clamps_and_uses_directional_progress():
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    events = player.set_frame(99)
    assert player.frame == 1
    assert events[0].kind == "frame_changed"


def test_view_exposes_region_offset_center_and_flips_without_backend_objects():
    component = AnimatedSprite2DComponent(
        frames(),
        animation="walk",
        centered=False,
        offset=(3.0, 4.0),
        flip_h=True,
        flip_v=True,
        layer=7,
    )
    view = AnimatedSpritePlayer2D(component).view
    assert view is not None
    assert view.asset_id == "hero.png"
    assert view.region == SpriteRegion(0, 0, 16, 16)
    assert view.offset == (3.0, 4.0)
    assert view.flip_h and view.flip_v
    assert view.layer == 7


@pytest.mark.parametrize("delta", [-1.0, math.inf, math.nan])
def test_invalid_deltas_are_rejected(delta):
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    player.play()
    with pytest.raises(ValueError):
        player.advance(delta)


def test_pause_resume_stop_and_negative_speed_preserve_runtime_only_state():
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    player.play()
    player.advance(0.05)
    player.pause()
    paused = (player.frame, player.frame_progress)
    player.advance(0.5)
    assert (player.frame, player.frame_progress) == paused
    player.play_backwards()
    assert player.playing_speed < 0.0
    player.stop()
    assert not player.playing
    assert (player.frame, player.frame_progress) == (0, 0.0)


def test_missing_and_empty_frame_collections_are_safe_and_invalid_timing_is_rejected():
    with pytest.raises(ValueError):
        SpriteFrame2D("hero.png", duration=0.0)
    with pytest.raises(ValueError):
        SpriteAnimation2D((SpriteFrame2D("hero.png"),), speed_fps=float("nan"))
    player = AnimatedSpritePlayer2D(AnimatedSprite2DComponent(frames(), animation="walk"))
    with pytest.raises(ValueError):
        player.set_animation("missing")
    events = player.set_frames(SpriteFrames2D())
    assert events[0].kind == "sprite_frames_changed"
    assert player.view is None
