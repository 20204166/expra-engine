"""Renderer-neutral 2D spatial-audio configuration and runtime math.

This module combines the useful behavior of Godot AudioStreamPlayer2D and
AudioListener2D without importing an audio backend, physics server, viewport,
or scene-tree singleton.

Expra ownership is preserved:
- AudioBus/AudioClip/AudioMixer remain canonical generic audio contracts.
- Components contain serializable configuration only.
- ``Audio2DWorld`` resolves listener selection, attenuation, panning and buses.
- ``AudioStreamPlayer2DState`` owns transient play/seek/pause/polyphony state.
- A backend can consume ``AudioPlaybackRequest2D`` without being imported here.
- optional area-bus routing is injected instead of duplicating PhysicsWorld2D.

Godot Engine source is MIT licensed:
Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md).
Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from expra_engine.core.component import Component
from expra_engine.core.scene import Scene
from expra_engine.runtime.audio import AudioClip, AudioMixer
from expra_engine.runtime.events import SceneContinued, SceneStarted, SceneStopped, Update
from expra_engine.runtime.system import RuntimeSystem

if TYPE_CHECKING:
    from expra_engine.core.engine import Engine

__all__ = (
    "Audio2DListener",
    "Audio2DSystem",
    "Audio2DWorld",
    "AudioListener2DComponent",
    "AudioPlaybackRequest2D",
    "AudioStreamPlayer2DComponent",
    "AudioStreamPlayer2DState",
    "PlaybackType2D",
    "SpatialAudioMix2D",
    "db_to_linear",
    "linear_to_db",
)

Pose2D = tuple[float, float, float]
PoseResolver = Callable[[str], Pose2D]
AreaBusResolver = Callable[[str, int], str | None]


class PlaybackType2D(StrEnum):
    DEFAULT = "default"
    STREAM = "stream"
    SAMPLE = "sample"


def _finite(value: object, name: str) -> float:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _non_negative(value: object, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _integer(value: object, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        converted = int(cast(Any, value))
        if float(cast(Any, value)) != converted:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if converted < minimum or (maximum is not None and converted > maximum):
        raise ValueError(f"{name} is outside its allowed range")
    return converted


def _bus(value: object) -> str:
    name = str(value)
    try:
        AudioMixer().bus(name)
    except KeyError as exc:
        raise ValueError(f"unknown audio bus: {name!r}") from exc
    return name


def db_to_linear(db: float) -> float:
    value = _finite(db, "volume_db")
    return 10.0 ** (value / 20.0)


def linear_to_db(linear: float) -> float:
    value = _non_negative(linear, "volume_linear")
    if value == 0.0:
        return float("-inf")
    return 20.0 * math.log10(value)


class AudioListener2DComponent(Component):
    """Serializable listener preference.

    Multiple ``current=True`` listeners are allowed in data so malformed or
    merged scenes remain loadable; ``Audio2DWorld`` deterministically chooses
    the first enabled one in scene order.
    """

    component_type = "audio_listener_2d"

    def __init__(self, *, current: bool = False, enabled: bool = True) -> None:
        super().__init__(enabled=enabled)
        self.current = bool(current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "current": self.current,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioListener2DComponent:
        return cls(
            current=bool(data.get("current", False)),
            enabled=bool(data.get("enabled", True)),
        )


class AudioStreamPlayer2DComponent(Component):
    """Serializable spatial-audio source configuration."""

    component_type = "audio_stream_player_2d"

    def __init__(
        self,
        asset_id: str | None = None,
        *,
        volume_db: float = 0.0,
        pitch_scale: float = 1.0,
        autoplay: bool = False,
        stream_paused: bool = False,
        max_distance: float = 2000.0,
        attenuation: float = 1.0,
        max_polyphony: int = 1,
        panning_strength: float = 1.0,
        bus: str = "sfx",
        area_mask: int = 0,
        playback_type: PlaybackType2D | str = PlaybackType2D.DEFAULT,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.asset_id = None if asset_id in (None, "") else str(asset_id)
        self.volume_db = _finite(volume_db, "volume_db")
        self.pitch_scale = _positive(pitch_scale, "pitch_scale")
        self.autoplay = bool(autoplay)
        self.stream_paused = bool(stream_paused)
        self.max_distance = _positive(max_distance, "max_distance")
        self.attenuation = _non_negative(attenuation, "attenuation")
        self.max_polyphony = _integer(max_polyphony, "max_polyphony", minimum=1)
        self.panning_strength = _non_negative(panning_strength, "panning_strength")
        self.bus = _bus(bus)
        self.area_mask = _integer(area_mask, "area_mask", maximum=0xFFFFFFFF)
        self.playback_type = (
            playback_type
            if isinstance(playback_type, PlaybackType2D)
            else PlaybackType2D(str(playback_type))
        )

    @property
    def volume_linear(self) -> float:
        return db_to_linear(self.volume_db)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "asset_id": self.asset_id,
            "volume_db": self.volume_db,
            "pitch_scale": self.pitch_scale,
            "autoplay": self.autoplay,
            "stream_paused": self.stream_paused,
            "max_distance": self.max_distance,
            "attenuation": self.attenuation,
            "max_polyphony": self.max_polyphony,
            "panning_strength": self.panning_strength,
            "bus": self.bus,
            "area_mask": self.area_mask,
            "playback_type": self.playback_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioStreamPlayer2DComponent:
        return cls(
            data.get("asset_id"),
            volume_db=data.get("volume_db", 0.0),
            pitch_scale=data.get("pitch_scale", 1.0),
            autoplay=bool(data.get("autoplay", False)),
            stream_paused=bool(data.get("stream_paused", False)),
            max_distance=data.get("max_distance", 2000.0),
            attenuation=data.get("attenuation", 1.0),
            max_polyphony=data.get("max_polyphony", 1),
            panning_strength=data.get("panning_strength", 1.0),
            bus=str(data.get("bus", "sfx")),
            area_mask=data.get("area_mask", 0),
            playback_type=str(data.get("playback_type", PlaybackType2D.DEFAULT.value)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class Audio2DListener:
    entity_id: str | None
    position: tuple[float, float]
    rotation: float = 0.0

    def __post_init__(self) -> None:
        x = _finite(self.position[0], "listener.x")
        y = _finite(self.position[1], "listener.y")
        object.__setattr__(self, "position", (x, y))
        object.__setattr__(self, "rotation", _finite(self.rotation, "listener.rotation"))


@dataclass(frozen=True)
class SpatialAudioMix2D:
    source_entity_id: str
    listener_entity_id: str | None
    audible: bool
    distance: float
    gain: float
    pan: float
    left_gain: float
    right_gain: float
    bus: str
    pitch_scale: float

    def __post_init__(self) -> None:
        if not self.source_entity_id:
            raise ValueError("source_entity_id must not be empty")
        if not -1.0 <= self.pan <= 1.0:
            raise ValueError("pan must be in [-1, 1]")
        for name in ("distance", "gain", "left_gain", "right_gain"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class AudioPlaybackRequest2D:
    """Backend-neutral snapshot for one source's current playback."""

    entity_id: str
    asset_id: str
    voice_positions: tuple[float, ...]
    paused: bool
    playback_type: PlaybackType2D
    max_polyphony: int
    mix: SpatialAudioMix2D


class AudioStreamPlayer2DState:
    """Transient caller-driven play/seek/pause/polyphony state.

    This deliberately does not guess clip duration or emit ``finished``;
    only the backend/decoded stream knows when playback actually ends.
    """

    def __init__(self, component: AudioStreamPlayer2DComponent) -> None:
        if not isinstance(component, AudioStreamPlayer2DComponent):
            raise TypeError("component must be AudioStreamPlayer2DComponent")
        self.component = component
        self._voices: list[float] = []
        self._paused = component.stream_paused

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def voices(self) -> tuple[float, ...]:
        return tuple(self._voices)

    @property
    def is_playing(self) -> bool:
        return bool(self._voices)

    @property
    def playback_position(self) -> float:
        return self._voices[-1] if self._voices else 0.0

    def autoplay(self) -> bool:
        return self.play(0.0) if self.component.autoplay else False

    def play(self, from_position: float = 0.0) -> bool:
        position = _non_negative(from_position, "from_position")
        if not self.component.enabled or not self.component.asset_id:
            return False
        self._voices.append(position)
        overflow = len(self._voices) - self.component.max_polyphony
        if overflow > 0:
            del self._voices[:overflow]
        return True

    def seek(self, seconds: float) -> None:
        position = _non_negative(seconds, "seconds")
        self._voices = [position for _ in self._voices]

    def stop(self) -> None:
        self._voices.clear()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    def advance(self, delta: float) -> None:
        value = _non_negative(delta, "delta")
        if self._paused or not self._voices:
            return
        step = value * self.component.pitch_scale
        self._voices = [position + step for position in self._voices]


class Audio2DWorld:
    """Resolve listener selection and spatial mix over an Expra scene.

    ``pose_resolver`` is the seam for canonical hierarchy/global-transform
    ownership. Without one, the scene's authoritative world-pose query is used.

    ``area_bus_resolver`` is optional. It lets future Area audio-bus routing
    remain owned by PhysicsWorld2D/Area rather than duplicating overlap logic.
    """

    def __init__(
        self,
        scene: Scene,
        *,
        mixer: AudioMixer | None = None,
        pose_resolver: PoseResolver | None = None,
        area_bus_resolver: AreaBusResolver | None = None,
        global_panning_strength: float = 1.0,
    ) -> None:
        if not isinstance(scene, Scene):
            raise TypeError("scene must be a Scene")
        self.scene = scene
        self.mixer = mixer or AudioMixer()
        self.pose_resolver = pose_resolver or scene.world_pose
        self.area_bus_resolver = area_bus_resolver
        self.global_panning_strength = _non_negative(
            global_panning_strength, "global_panning_strength"
        )

    def current_listener(
        self,
        *,
        fallback_position: tuple[float, float] = (0.0, 0.0),
        fallback_rotation: float = 0.0,
    ) -> Audio2DListener:
        for entity in self.scene.entities:
            if not entity.enabled:
                continue
            listener = entity.get_component(AudioListener2DComponent)
            if listener is None or not listener.enabled or not listener.current:
                continue
            x, y, rotation = self.pose_resolver(entity.entity_id)
            return Audio2DListener(entity.entity_id, (x, y), rotation)
        return Audio2DListener(
            None,
            (
                _finite(fallback_position[0], "fallback_listener.x"),
                _finite(fallback_position[1], "fallback_listener.y"),
            ),
            _finite(fallback_rotation, "fallback_listener.rotation"),
        )

    def make_current(self, entity_id: str) -> None:
        target = self.scene.find_entity(entity_id)
        if target is None or not target.enabled:
            raise KeyError(f"listener entity not found: {entity_id!r}")
        listener = target.get_component(AudioListener2DComponent)
        if listener is None or not listener.enabled:
            raise ValueError("entity does not have an enabled AudioListener2DComponent")
        for entity in self.scene.entities:
            other = entity.get_component(AudioListener2DComponent)
            if other is not None:
                other.current = entity is target

    def clear_current(self, entity_id: str) -> bool:
        entity = self.scene.find_entity(entity_id)
        if entity is None:
            return False
        listener = entity.get_component(AudioListener2DComponent)
        if listener is None:
            return False
        was_current = listener.current
        listener.current = False
        return was_current

    def is_current(self, entity_id: str) -> bool:
        return self.current_listener().entity_id == entity_id

    def mix_for(
        self,
        entity_id: str,
        *,
        viewport_width: float,
        fallback_listener_position: tuple[float, float] = (0.0, 0.0),
        fallback_listener_rotation: float = 0.0,
    ) -> SpatialAudioMix2D:
        width = _positive(viewport_width, "viewport_width")
        entity = self.scene.find_entity(entity_id)
        if entity is None:
            raise KeyError(f"audio source not found: {entity_id!r}")
        source = entity.get_component(AudioStreamPlayer2DComponent)
        if source is None:
            raise ValueError("entity does not have AudioStreamPlayer2DComponent")
        volume_db = _finite(source.volume_db, "volume_db")
        pitch_scale = _positive(source.pitch_scale, "pitch_scale")
        max_distance = _positive(source.max_distance, "max_distance")
        attenuation = _non_negative(source.attenuation, "attenuation")
        panning_strength = _non_negative(source.panning_strength, "panning_strength")
        listener = self.current_listener(
            fallback_position=fallback_listener_position,
            fallback_rotation=fallback_listener_rotation,
        )
        bus = self._actual_bus(entity_id, source)
        if not entity.enabled or not source.enabled or not source.asset_id:
            return self._silent_mix(entity_id, listener.entity_id, bus, pitch_scale)

        sx, sy, _ = self.pose_resolver(entity_id)
        dx = sx - listener.position[0]
        dy = sy - listener.position[1]
        distance = math.hypot(dx, dy)
        if distance > max_distance:
            return SpatialAudioMix2D(
                entity_id,
                listener.entity_id,
                False,
                distance,
                0.0,
                0.0,
                0.0,
                0.0,
                bus,
                pitch_scale,
            )

        angle = math.radians(-listener.rotation)
        relative_x = dx * math.cos(angle) - dy * math.sin(angle)
        normalized = max(-1.0, min(1.0, relative_x / width))
        pan = max(
            -1.0,
            min(
                1.0,
                normalized * panning_strength * self.global_panning_strength * 0.5,
            ),
        )
        balance = (pan + 1.0) * 0.5

        distance_gain = max(0.0, 1.0 - distance / max_distance)
        distance_gain = distance_gain**attenuation
        clip = AudioClip(source.asset_id, bus=bus, pitch=pitch_scale)
        gain = distance_gain * db_to_linear(volume_db) * clip.effective_volume(self.mixer)
        left = (1.0 - balance) * gain
        right = balance * gain
        return SpatialAudioMix2D(
            entity_id,
            listener.entity_id,
            gain > 0.0,
            distance,
            gain,
            pan,
            left,
            right,
            bus,
            pitch_scale,
        )

    def playback_request(
        self,
        entity_id: str,
        state: AudioStreamPlayer2DState,
        *,
        viewport_width: float,
        fallback_listener_position: tuple[float, float] = (0.0, 0.0),
        fallback_listener_rotation: float = 0.0,
    ) -> AudioPlaybackRequest2D | None:
        component = state.component
        if not component.asset_id or not state.is_playing:
            return None
        mix = self.mix_for(
            entity_id,
            viewport_width=viewport_width,
            fallback_listener_position=fallback_listener_position,
            fallback_listener_rotation=fallback_listener_rotation,
        )
        return AudioPlaybackRequest2D(
            entity_id,
            component.asset_id,
            state.voices,
            state.paused,
            component.playback_type,
            component.max_polyphony,
            mix,
        )

    def _actual_bus(self, entity_id: str, source: AudioStreamPlayer2DComponent) -> str:
        if source.area_mask and self.area_bus_resolver is not None:
            override = self.area_bus_resolver(entity_id, source.area_mask)
            if override is not None:
                return _bus(override)
        return _bus(source.bus)

    @staticmethod
    def _silent_mix(
        source_id: str,
        listener_id: str | None,
        bus: str,
        pitch: float,
    ) -> SpatialAudioMix2D:
        return SpatialAudioMix2D(
            source_id,
            listener_id,
            False,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            bus,
            pitch,
        )


class Audio2DSystem(RuntimeSystem):
    """Own transient 2D audio state and expose backend-neutral requests."""

    def __init__(
        self,
        *,
        mixer: AudioMixer | None = None,
        viewport_width: float = 100.0,
        pose_resolver: PoseResolver | None = None,
        area_bus_resolver: AreaBusResolver | None = None,
        global_panning_strength: float = 1.0,
    ) -> None:
        self.mixer = mixer or AudioMixer()
        self.viewport_width = _positive(viewport_width, "viewport_width")
        self.pose_resolver = pose_resolver
        self.area_bus_resolver = area_bus_resolver
        self.global_panning_strength = _non_negative(
            global_panning_strength, "global_panning_strength"
        )
        self._engine: Engine | None = None
        self._world: Audio2DWorld | None = None
        self._states: dict[tuple[int, int], AudioStreamPlayer2DState] = {}

    @property
    def world(self) -> Audio2DWorld | None:
        return self._world

    @property
    def states(self) -> dict[str, AudioStreamPlayer2DState]:
        scene = self._active_scene()
        if scene is None:
            return {}
        return {
            entity.entity_id: state
            for entity in scene.entities
            for component in entity.get_components(AudioStreamPlayer2DComponent)
            if (state := self._states.get((id(scene), id(component)))) is not None
        }

    @property
    def playback_requests(self) -> tuple[AudioPlaybackRequest2D, ...]:
        scene = self._active_scene()
        world = self._world
        if scene is None or world is None:
            return ()
        requests: list[AudioPlaybackRequest2D] = []
        for entity in scene.entities:
            for component in entity.get_components(AudioStreamPlayer2DComponent):
                state = self._states.get((id(scene), id(component)))
                if state is None:
                    continue
                request = world.playback_request(
                    entity.entity_id,
                    state,
                    viewport_width=self.viewport_width,
                )
                if request is not None:
                    requests.append(request)
        return tuple(requests)

    @property
    def requests(self) -> tuple[AudioPlaybackRequest2D, ...]:
        """Alias for consumers that treat requests as the primary output."""
        return self.playback_requests

    def state_for(self, entity_id: str) -> AudioStreamPlayer2DState | None:
        scene = self._active_scene()
        if scene is None:
            return None
        entity = scene.find_entity(entity_id)
        if entity is None:
            return None
        component = entity.get_component(AudioStreamPlayer2DComponent)
        return self._states.get((id(scene), id(component))) if component is not None else None

    def play(self, entity_id: str, from_position: float = 0.0) -> bool:
        state = self.state_for(entity_id)
        return state.play(from_position) if state is not None else False

    def seek(self, entity_id: str, seconds: float) -> bool:
        state = self.state_for(entity_id)
        if state is None:
            return False
        state.seek(seconds)
        return True

    def stop_source(self, entity_id: str) -> bool:
        state = self.state_for(entity_id)
        if state is None:
            return False
        state.stop()
        return True

    def set_paused(self, entity_id: str, paused: bool) -> bool:
        state = self.state_for(entity_id)
        if state is None:
            return False
        state.set_paused(paused)
        return True

    def start(self, engine: Engine) -> None:
        self._engine = engine

    def stop(self) -> None:
        self._states.clear()
        self._world = None
        self._engine = None

    def on_scene_started(self, _event: SceneStarted, _signal: Any) -> None:
        self._activate_scene(self._active_scene(), start_autoplay=True)

    def on_scene_continued(self, _event: SceneContinued, _signal: Any) -> None:
        self._activate_scene(self._active_scene(), start_autoplay=False)

    def on_scene_stopped(self, _event: SceneStopped, _signal: Any) -> None:
        scene = self._active_scene()
        if scene is not None:
            self._remove_scene(scene)
        self._world = None

    def on_update(self, event: Update, _signal: Any) -> None:
        scene = self._active_scene()
        self._activate_scene(scene, start_autoplay=True)
        if scene is None:
            return
        for entity in scene.entities:
            if not entity.enabled:
                continue
            for component in entity.get_components(AudioStreamPlayer2DComponent):
                state = self._states.get((id(scene), id(component)))
                if state is not None and component.enabled:
                    state.advance(event.time_delta)

    def on_frame_update(self, _event: Any, _signal: Any) -> None:
        """Reconcile source membership even when no fixed update is due."""
        self._activate_scene(self._active_scene(), start_autoplay=True)

    def _active_scene(self) -> Scene | None:
        return self._engine.active_scene if self._engine is not None else None

    def _activate_scene(self, scene: Scene | None, *, start_autoplay: bool) -> None:
        if scene is None:
            self._world = None
            return
        if self._world is None or self._world.scene is not scene:
            self._world = Audio2DWorld(
                scene,
                mixer=self.mixer,
                pose_resolver=self.pose_resolver,
                area_bus_resolver=self.area_bus_resolver,
                global_panning_strength=self.global_panning_strength,
            )
        active_keys: set[tuple[int, int]] = set()
        for entity in scene.entities:
            for component in entity.get_components(AudioStreamPlayer2DComponent):
                key = (id(scene), id(component))
                if not entity.enabled or not component.enabled:
                    self._states.pop(key, None)
                    continue
                active_keys.add(key)
                if key not in self._states:
                    state = self._states[key] = AudioStreamPlayer2DState(component)
                    if start_autoplay:
                        state.autoplay()
        for key in tuple(self._states):
            if key[0] == id(scene) and key not in active_keys:
                del self._states[key]

    def _remove_scene(self, scene: Scene) -> None:
        for key in tuple(self._states):
            if key[0] == id(scene):
                del self._states[key]
