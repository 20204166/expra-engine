"""Runtime ownership for transient AnimatedSprite2D playback state."""

from __future__ import annotations

import json
import weakref
from typing import TYPE_CHECKING, Any

from expra_engine.core.scene import Scene
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
    SpriteEvent2D,
    SpriteFrames2D,
)
from expra_engine.runtime.events import SceneContinued, SceneStarted, SceneStopped, Update
from expra_engine.runtime.system import RuntimeSystem

if TYPE_CHECKING:
    from expra_engine.core.engine import Engine
    from expra_engine.core.entity import Entity

__all__ = ("AnimatedSpriteSystem",)

_TARGET = "runtime:animation:update"


class AnimatedSpriteSystem(RuntimeSystem):
    """Maintain one runtime player for each active scene animated sprite."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._players: dict[tuple[int, int], AnimatedSpritePlayer2D] = {}
        self._frame_signatures: weakref.WeakKeyDictionary[SpriteFrames2D, str] = (
            weakref.WeakKeyDictionary()
        )
        self._observer: ObservabilityWatcher | None = None

    @property
    def players(self) -> dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D]:
        scene = self._active_scene()
        if scene is None:
            return {}
        players: dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] = {}
        scene_key = id(scene)
        for entity in scene.iter_entities_by_component(AnimatedSprite2DComponent):
            for component in entity.get_components(AnimatedSprite2DComponent):
                player = self._players.get((scene_key, id(component)))
                if player is not None:
                    players[component] = player
        return players

    def player_for(self, component: AnimatedSprite2DComponent) -> AnimatedSpritePlayer2D | None:
        return self.players.get(component)

    def start(self, engine: Engine) -> None:
        self._engine = engine
        self._observer = getattr(engine, "observer", None)

    def stop(self) -> None:
        self._players.clear()
        self._frame_signatures.clear()
        self._engine = None
        self._observer = None

    def on_scene_started(self, _event: SceneStarted, signal: Any) -> None:
        self._reconcile(self._active_scene(), start_autoplay=True, signal=signal)

    def on_scene_continued(self, _event: SceneContinued, signal: Any) -> None:
        self._reconcile(self._active_scene(), start_autoplay=False, signal=signal)

    def on_scene_stopped(self, _event: SceneStopped, _signal: Any) -> None:
        scene = self._active_scene()
        if scene is not None:
            self._remove_scene(scene)

    def on_world_level_activated(
        self, world_scene: Scene, _level_id: str, _entity_ids: tuple[str, ...]
    ) -> None:
        signal = self._engine.signal if self._engine is not None else lambda *_args: None
        self._reconcile(world_scene, start_autoplay=True, signal=signal)

    def on_world_level_deactivated(
        self, world_scene: Scene, _level_id: str, entity_ids: tuple[str, ...]
    ) -> None:
        for entity_id in entity_ids:
            entity = world_scene.find_entity(entity_id)
            if entity is None:
                continue
            for component in entity.get_components(AnimatedSprite2DComponent):
                player = self._players.pop((id(world_scene), id(component)), None)
                if player is not None:
                    player.stop()

    def on_update(self, event: Update, signal: Any) -> None:
        observer = self._observer
        token = observer.begin(_TARGET) if observer is not None else None
        advanced = 0
        transitions = 0
        try:
            scene = self._active_scene()
            if scene is None:
                self._players.clear()
                return
            scene_key = id(scene)
            active_keys: set[tuple[int, int]] = set()
            active_players: list[
                tuple[Entity, AnimatedSprite2DComponent, AnimatedSpritePlayer2D]
            ] = []
            animated_entities = tuple(
                scene.iter_entities_by_component(AnimatedSprite2DComponent)
            )
            for entity in animated_entities:
                for component in entity.get_components(AnimatedSprite2DComponent):
                    key = (scene_key, id(component))
                    if not entity.enabled or not component.enabled:
                        self._players.pop(key, None)
                        continue
                    active_keys.add(key)
                    player = self._players.get(key)
                    if player is None:
                        player = self._players[key] = AnimatedSpritePlayer2D(component)
                        self._record(entity, player.start(), signal)
                    elif player.frames is not component.frames:
                        self._record(entity, player.set_frames(component.frames), signal)
                    active_players.append((entity, component, player))
            for key in tuple(self._players):
                if key[0] == scene_key and key not in active_keys:
                    del self._players[key]

            groups: dict[
                tuple[object, ...],
                list[tuple[Entity, AnimatedSprite2DComponent, AnimatedSpritePlayer2D]],
            ] = {}
            for entry in active_players:
                player = entry[2]
                signature = (
                    self._frames_signature(player.frames),
                    player.animation,
                    player.frame,
                    player.frame_progress,
                    player.speed_scale,
                    player.custom_speed_scale,
                    player.playing,
                )
                groups.setdefault(signature, []).append(entry)

            events_by_component: dict[int, tuple[SpriteEvent2D, ...]] = {}
            for entries in groups.values():
                leader = entries[0][2]
                events = leader.advance(event.time_delta)
                advanced += len(entries)
                transitions += len(events) * len(entries)
                for _entity, component, player in entries:
                    player.frame_progress = leader.frame_progress
                    if events:
                        player.animation = leader.animation
                        player.frame = leader.frame
                        player.speed_scale = leader.speed_scale
                        player.custom_speed_scale = leader.custom_speed_scale
                        player.playing = leader.playing
                        events_by_component[id(component)] = events

            for entity, component, _player in active_players:
                if events := events_by_component.get(id(component)):
                    self._record(entity, events, signal)
        finally:
            if observer is not None:
                observer.set_gauge(_TARGET, "active_players", len(self._players))
                observer.increment(_TARGET, "players_advanced", advanced)
                observer.increment(_TARGET, "frame_transitions", transitions)
                if token is not None:
                    observer.finish(token)

    def on_frame_update(self, _event: Any, signal: Any) -> None:
        """Reconcile live entities even when no fixed update is due."""
        self._reconcile(self._active_scene(), start_autoplay=True, signal=signal)

    def _active_scene(self) -> Scene | None:
        return self._engine.active_scene if self._engine is not None else None

    def _reconcile(self, scene: Scene | None, *, start_autoplay: bool, signal: Any) -> None:
        if scene is None:
            self._players.clear()
            return
        active_keys: set[tuple[int, int]] = set()
        for entity in scene.iter_entities_by_component(AnimatedSprite2DComponent):
            for component in entity.get_components(AnimatedSprite2DComponent):
                key = (id(scene), id(component))
                if not entity.enabled or not component.enabled:
                    self._players.pop(key, None)
                    continue
                active_keys.add(key)
                player = self._players.get(key)
                if player is None:
                    player = self._players[key] = AnimatedSpritePlayer2D(component)
                    if start_autoplay:
                        self._record(entity, player.start(), signal)
                    continue
                if player.frames is not component.frames:
                    self._record(entity, player.set_frames(component.frames), signal)
        for key in tuple(self._players):
            if key[0] == id(scene) and key not in active_keys:
                del self._players[key]

    def _remove_scene(self, scene: Scene) -> None:
        for key in tuple(self._players):
            if key[0] == id(scene):
                del self._players[key]

    def _frames_signature(self, frames: SpriteFrames2D) -> str:
        signature = self._frame_signatures.get(frames)
        if signature is None:
            signature = json.dumps(frames.to_dict(), sort_keys=True, separators=(",", ":"))
            self._frame_signatures[frames] = signature
        return signature

    @staticmethod
    def _record(entity: Any, events: tuple[SpriteEvent2D, ...], signal: Any) -> None:
        for event in events:
            signal(event, targets=(entity,))
