"""Focused tests for the 2D spatial-audio conversion."""

import math

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.audio import AudioMixer
from expra_engine.runtime.audio_2d import (
    Audio2DWorld,
    AudioListener2DComponent,
    AudioStreamPlayer2DComponent,
    AudioStreamPlayer2DState,
    PlaybackType2D,
    db_to_linear,
    linear_to_db,
)


def scene_with_source_and_listener():
    scene = Scene("audio")
    listener = scene.create_entity("listener", entity_id="listener")
    listener.add_component(TransformComponent(x=0.0, y=0.0))
    listener.add_component(AudioListener2DComponent(current=True))
    source = scene.create_entity("source", entity_id="source")
    source.add_component(TransformComponent(x=10.0, y=0.0))
    source.add_component(
        AudioStreamPlayer2DComponent(
            "laser.wav",
            max_distance=100.0,
            panning_strength=1.0,
            bus="sfx",
        )
    )
    return scene, source, listener


def test_component_round_trip_preserves_config():
    source = AudioStreamPlayer2DComponent(
        "ambience.ogg",
        volume_db=-6.0,
        pitch_scale=1.2,
        autoplay=True,
        stream_paused=True,
        max_distance=500.0,
        attenuation=2.0,
        max_polyphony=4,
        panning_strength=0.75,
        bus="ambience",
        area_mask=3,
        playback_type=PlaybackType2D.STREAM,
    )
    assert AudioStreamPlayer2DComponent.from_dict(source.to_dict()).to_dict() == source.to_dict()


def test_listener_first_current_wins_deterministically():
    scene, _, first = scene_with_source_and_listener()
    second = scene.create_entity("second", entity_id="second")
    second.add_component(AudioListener2DComponent(current=True))
    assert Audio2DWorld(scene).current_listener().entity_id == first.entity_id


def test_make_current_clears_other_listener_flags():
    scene, _, first = scene_with_source_and_listener()
    second = scene.create_entity("second", entity_id="second")
    second.add_component(AudioListener2DComponent())
    world = Audio2DWorld(scene)
    world.make_current("second")
    assert world.is_current("second")
    assert first.get_component(AudioListener2DComponent).current is False


def test_distance_attenuation_and_pan_are_resolved():
    scene, _, _ = scene_with_source_and_listener()
    mix = Audio2DWorld(scene).mix_for("source", viewport_width=100.0)
    assert mix.audible
    assert mix.distance == pytest.approx(10.0)
    assert mix.gain == pytest.approx(0.9)
    assert mix.pan > 0.0
    assert mix.right_gain > mix.left_gain


def test_outside_max_distance_is_silent():
    scene, source, _ = scene_with_source_and_listener()
    source.get_component(TransformComponent).x = 101.0
    mix = Audio2DWorld(scene).mix_for("source", viewport_width=100.0)
    assert not mix.audible
    assert mix.gain == 0.0


def test_bus_and_master_volume_affect_gain():
    scene, _, _ = scene_with_source_and_listener()
    mixer = AudioMixer()
    mixer.bus("master").set_volume(0.5)
    mixer.bus("sfx").set_volume(0.5)
    mix = Audio2DWorld(scene, mixer=mixer).mix_for("source", viewport_width=100.0)
    assert mix.gain == pytest.approx(0.9 * 0.25)


def test_area_bus_override_is_injected_not_physics_duplicated():
    scene, source, _ = scene_with_source_and_listener()
    component = source.get_component(AudioStreamPlayer2DComponent)
    component.area_mask = 1
    world = Audio2DWorld(scene, area_bus_resolver=lambda entity_id, mask: "ambience")
    assert world.mix_for("source", viewport_width=100.0).bus == "ambience"


def test_polyphony_drops_oldest_voice_and_seek_updates_remaining_voices():
    component = AudioStreamPlayer2DComponent("shot.wav", max_polyphony=2)
    state = AudioStreamPlayer2DState(component)
    state.play(1.0)
    state.play(2.0)
    state.play(3.0)
    assert state.voices == (2.0, 3.0)
    state.seek(5.0)
    assert state.voices == (5.0, 5.0)


def test_pause_and_pitch_affect_transient_position():
    component = AudioStreamPlayer2DComponent("tone.wav", pitch_scale=2.0)
    state = AudioStreamPlayer2DState(component)
    state.play()
    state.advance(0.5)
    assert state.playback_position == pytest.approx(1.0)
    state.set_paused(True)
    state.advance(1.0)
    assert state.playback_position == pytest.approx(1.0)


def test_playback_request_combines_state_and_spatial_mix():
    scene, source, _ = scene_with_source_and_listener()
    component = source.get_component(AudioStreamPlayer2DComponent)
    state = AudioStreamPlayer2DState(component)
    state.play(0.25)
    request = Audio2DWorld(scene).playback_request("source", state, viewport_width=100.0)
    assert request is not None
    assert request.asset_id == "laser.wav"
    assert request.voice_positions == (0.25,)
    assert request.mix.source_entity_id == "source"


def test_db_linear_conversion_round_trip():
    assert linear_to_db(db_to_linear(-12.0)) == pytest.approx(-12.0)
    assert linear_to_db(0.0) == float("-inf")


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_non_finite_spatial_settings_are_rejected(bad):
    with pytest.raises(ValueError):
        AudioStreamPlayer2DComponent("x.wav", max_distance=bad)
