"""Integration coverage for native Expra 2D audio ownership."""

import json
import math

import pytest

from expra_engine.core.component import (
    TransformComponent,
    component_from_dict,
    registered_component_types,
)
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.engine import Engine
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime.audio import AudioMixer
from expra_engine.runtime.audio_2d import (
    Audio2DSystem,
    Audio2DWorld,
    AudioListener2DComponent,
    AudioStreamPlayer2DComponent,
    AudioStreamPlayer2DState,
)


def _scene() -> tuple[Scene, Entity, Entity]:
    scene = Scene("audio")
    listener = scene.create_entity("listener", entity_id="listener")
    listener.add_component(TransformComponent())
    listener.add_component(AudioListener2DComponent(current=True))
    source = scene.create_entity("source", entity_id="source")
    source.add_component(TransformComponent(x=10.0))
    source.add_component(
        AudioStreamPlayer2DComponent("laser.wav", max_distance=10.0, attenuation=0.0)
    )
    return scene, listener, source


def test_audio_components_are_registered_with_inspector_metadata() -> None:
    registered = dict(registered_component_types())
    assert registered["audio_listener_2d"] is AudioListener2DComponent
    assert registered["audio_stream_player_2d"] is AudioStreamPlayer2DComponent
    assert tuple(field.name for field in component_type_spec("audio_listener_2d").fields) == (
        "current",
        "enabled",
    )
    assert {field.name for field in component_type_spec("audio_stream_player_2d").fields} >= {
        "asset_id",
        "volume_db",
        "pitch_scale",
        "autoplay",
        "stream_paused",
        "max_distance",
        "attenuation",
        "max_polyphony",
        "panning_strength",
        "bus",
        "area_mask",
        "playback_type",
        "enabled",
    }


def test_audio_components_and_full_scene_round_trip_without_runtime_state() -> None:
    scene, listener, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    listener_component = listener.get_component(AudioListener2DComponent)
    assert component is not None and listener_component is not None
    state = AudioStreamPlayer2DState(component)
    state.play(2.0)

    payload = json.loads(json.dumps(scene.to_dict()))
    loaded = Scene.from_dict(payload)

    assert loaded.to_dict() == scene.to_dict()
    assert (
        component_from_dict(listener_component.to_dict()).to_dict() == listener_component.to_dict()
    )
    assert "voices" not in json.dumps(payload)
    assert "playback_position" not in json.dumps(payload)


def test_scene_world_pose_composes_parent_transform_for_audio() -> None:
    scene = Scene("hierarchy")
    parent = scene.create_entity("parent", entity_id="parent")
    parent.add_component(TransformComponent(x=5.0, rotation=90.0, scale_x=2.0, scale_y=2.0))
    child = scene.create_entity("child", entity_id="child", parent_id="parent")
    child.add_component(TransformComponent(x=3.0, rotation=10.0))

    assert scene.world_pose("child") == pytest.approx((5.0, 6.0, 100.0))
    assert Audio2DWorld(scene).pose_resolver("child") == pytest.approx((5.0, 6.0, 100.0))


def test_scene_world_pose_rejects_malformed_cycles() -> None:
    scene = Scene("cycle")
    first = scene.create_entity("first", entity_id="first", parent_id="second")
    second = scene.create_entity("second", entity_id="second", parent_id="first")
    first.add_component(TransformComponent())
    second.add_component(TransformComponent())

    with pytest.raises(ValueError, match="cycle"):
        scene.world_pose("first")


def test_disabled_listener_and_source_use_fallback_and_silence() -> None:
    scene, listener, source = _scene()
    world = Audio2DWorld(scene)
    listener.enabled = False
    assert world.current_listener(fallback_position=(4.0, 5.0)).entity_id is None
    assert world.current_listener(fallback_position=(4.0, 5.0)).position == (4.0, 5.0)

    source.enabled = False
    mix = world.mix_for("source", viewport_width=100.0)
    assert not mix.audible
    assert mix.gain == 0.0


def test_make_current_and_clear_current_have_deterministic_ownership() -> None:
    scene, listener, _ = _scene()
    second = scene.create_entity("second", entity_id="second")
    second.add_component(AudioListener2DComponent())
    world = Audio2DWorld(scene)
    world.make_current("second")
    assert world.is_current("second")
    listener_component = listener.get_component(AudioListener2DComponent)
    assert listener_component is not None and not listener_component.current
    assert world.clear_current("second")
    assert not world.is_current("second")


def test_missing_listener_uses_finite_fallback_and_panning_is_left_center_right() -> None:
    scene = Scene("fallback")
    source = scene.create_entity("source", entity_id="source")
    source.add_component(TransformComponent())
    source.add_component(
        AudioStreamPlayer2DComponent("tone.wav", max_distance=1000.0, panning_strength=2.0)
    )
    world = Audio2DWorld(scene)
    transform = source.get_component(TransformComponent)
    assert transform is not None

    transform.x = -100.0
    assert world.mix_for("source", viewport_width=100.0).pan == pytest.approx(-1.0)
    transform.x = 0.0
    assert world.mix_for("source", viewport_width=100.0).pan == pytest.approx(0.0)
    transform.x = 100.0
    assert world.mix_for("source", viewport_width=100.0).pan == pytest.approx(1.0)
    assert world.current_listener(fallback_position=(2.0, 3.0)).position == (2.0, 3.0)
    with pytest.raises(ValueError):
        world.current_listener(fallback_position=(math.nan, 0.0))


def test_bus_mute_and_source_db_volume_reuse_canonical_mixer_gain() -> None:
    scene, _, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    assert component is not None
    component.volume_db = -6.0
    mixer = AudioMixer()
    world = Audio2DWorld(scene, mixer=mixer)
    expected = 10.0 ** (-6.0 / 20.0)
    assert world.mix_for("source", viewport_width=100.0).gain == pytest.approx(expected)
    mixer.bus("sfx").muted = True
    assert world.mix_for("source", viewport_width=100.0).gain == 0.0


def test_spatial_edges_rotation_pan_clamp_and_gain_controls() -> None:
    scene, listener, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    transform = source.get_component(TransformComponent)
    assert component is not None and transform is not None
    listener_transform = listener.get_component(TransformComponent)
    assert listener_transform is not None
    transform.x = 0.0
    transform.y = 10.0
    listener_transform.rotation = 90.0
    component.panning_strength = 10.0
    world = Audio2DWorld(scene, mixer=AudioMixer(), global_panning_strength=2.0)

    centre = world.mix_for("source", viewport_width=100.0)
    assert centre.distance == pytest.approx(10.0)
    assert centre.pan == pytest.approx(1.0)
    assert centre.right_gain > centre.left_gain

    transform.x = 10.0
    transform.y = 0.0
    listener_transform.rotation = 0.0
    edge = world.mix_for("source", viewport_width=100.0)
    assert edge.audible
    assert edge.gain == pytest.approx(1.0)
    transform.x = 10.000001
    assert not world.mix_for("source", viewport_width=100.0).audible

    component.volume_db = -6.0
    world.mixer.bus("master").muted = True
    assert world.mix_for("source", viewport_width=100.0).gain == 0.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_audio_world_rejects_non_finite_controls(bad: float) -> None:
    scene, _, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    assert component is not None
    with pytest.raises(ValueError):
        component.max_distance = bad
        Audio2DWorld(scene).mix_for("source", viewport_width=100.0)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AudioStreamPlayer2DComponent("x.wav", pitch_scale=0.0),
        lambda: AudioStreamPlayer2DComponent("x.wav", max_polyphony=0),
        lambda: AudioStreamPlayer2DComponent("x.wav", area_mask=-1),
    ],
)
def test_audio_component_rejects_invalid_runtime_controls(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_audio_system_is_engine_owned_and_emits_requests_without_serializing_state() -> None:
    scene, _, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    assert component is not None
    component.autoplay = True
    engine = Engine()
    engine.set_scene(scene)
    system = engine.audio_2d_system
    assert isinstance(system, Audio2DSystem)

    engine.play()
    assert system.state_for("source") is not None
    assert system.playback_requests[0].asset_id == "laser.wav"
    active_scene = engine.active_scene
    assert active_scene is not None
    assert "voices" not in json.dumps(active_scene.to_dict())
    engine.tick(0.5)
    state = system.state_for("source")
    assert state is not None and state.playback_position == pytest.approx(0.5)
    engine.stop()
    assert system.playback_requests == ()


def test_audio_system_commands_pause_seek_stop_and_enforce_polyphony() -> None:
    scene, _, source = _scene()
    component = source.get_component(AudioStreamPlayer2DComponent)
    assert component is not None
    component.max_polyphony = 2
    engine = Engine()
    engine.set_scene(scene)
    system = engine.audio_2d_system
    engine.play()

    assert system.play("source", 1.0)
    assert system.play("source", 2.0)
    assert system.play("source", 3.0)
    state = system.state_for("source")
    assert state is not None and state.voices == (2.0, 3.0)
    assert system.seek("source", 5.0)
    assert state.voices == (5.0, 5.0)
    assert system.set_paused("source", True)
    engine.tick(0.5)
    assert state.playback_position == pytest.approx(5.0)
    assert system.stop_source("source")
    assert system.playback_requests == ()


def test_audio_system_cleans_removed_sources_at_frame_boundary() -> None:
    scene, _, source = _scene()
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    assert engine.audio_2d_system.state_for("source") is not None

    active_scene = engine.active_scene
    assert active_scene is not None
    assert active_scene.remove_entity(source.entity_id)
    engine.tick(0.0)

    assert engine.audio_2d_system.state_for("source") is None
    assert engine.audio_2d_system.states == {}


def test_audio_system_replaces_and_pushes_scenes_without_leaking_requests() -> None:
    scene, _, _ = _scene()
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    base_state = engine.audio_2d_system.state_for("source")
    assert base_state is not None
    base_state.play(4.0)

    overlay = Scene("overlay")
    overlay_source = overlay.create_entity("overlay-source", entity_id="overlay-source")
    overlay_source.add_component(TransformComponent(x=-5.0))
    overlay_source.add_component(AudioStreamPlayer2DComponent("overlay.wav", autoplay=True))
    engine.push_scene(overlay)
    assert [request.asset_id for request in engine.audio_2d_system.playback_requests] == [
        "overlay.wav"
    ]
    engine.pop_scene()
    base_state = engine.audio_2d_system.state_for("source")
    assert base_state is not None and base_state.playback_position == pytest.approx(4.0)

    replacement = Scene("replacement")
    replacement_source = replacement.create_entity("replacement", entity_id="replacement")
    replacement_source.add_component(AudioStreamPlayer2DComponent("replacement.wav", autoplay=True))
    engine.replace_scene(replacement)
    assert [request.asset_id for request in engine.audio_2d_system.playback_requests] == [
        "replacement.wav"
    ]
    engine.stop()
    assert engine.audio_2d_system.states == {}
