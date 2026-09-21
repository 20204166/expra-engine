"""Runtime ownership for transient AnimatedSprite2D playback state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
    SpriteEvent2D,
)
from expra_engine.runtime.events import SceneContinued, SceneStarted, SceneStopped, Update
from expra_engine.runtime.system import RuntimeSystem

if TYPE_CHECKING:
    from expra_engine.core.engine import Engine

__all__ = ("AnimatedSpriteSystem",)


class AnimatedSpriteSystem(RuntimeSystem):
    """Maintain one runtime player for each active scene animated sprite."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._players: dict[tuple[int, int], AnimatedSpritePlayer2D] = {}

    @property
    def players(self) -> dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D]:
        scene = self._active_scene()
        if scene is None:
            return {}
        return {
            component: player
            for (scene_key, component_key), player in self._players.items()
            for entity in scene.entities
            for component in entity.get_components(AnimatedSprite2DComponent)
            if scene_key == id(scene) and component_key == id(component)
        }

    def player_for(self, component: AnimatedSprite2DComponent) -> AnimatedSpritePlayer2D | None:
        return self.players.get(component)

    def start(self, engine: Engine) -> None:
        self._engine = engine

    def stop(self) -> None:
        self._players.clear()
        self._engine = None

    def on_scene_started(self, _event: SceneStarted, signal: Any) -> None:
        self._reconcile(self._active_scene(), start_autoplay=True, signal=signal)

    def on_scene_continued(self, _event: SceneContinued, signal: Any) -> None:
        self._reconcile(self._active_scene(), start_autoplay=False, signal=signal)

    def on_scene_stopped(self, _event: SceneStopped, _signal: Any) -> None:
        scene = self._active_scene()
        if scene is not None:
            self._remove_scene(scene)

    def on_update(self, event: Update, signal: Any) -> None:
        scene = self._active_scene()
        self._reconcile(scene, start_autoplay=True, signal=signal)
        if scene is None:
            return
        for entity in scene.entities:
            if not entity.enabled:
                continue
            for component in entity.get_components(AnimatedSprite2DComponent):
                player = self._players.get((id(scene), id(component)))
                if player is None or not component.enabled:
                    continue
                self._record(entity, player.advance(event.time_delta), signal)

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
        for entity in scene.entities:
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

    @staticmethod
    def _record(entity: Any, events: tuple[SpriteEvent2D, ...], signal: Any) -> None:
        for event in events:
            signal(event, targets=(entity,))
