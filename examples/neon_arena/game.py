"""Testable gameplay systems for the Neon Arena sample."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime import RuntimeSystem
from expra_engine.runtime.events import Update


def load_scene(path: Path) -> Scene:
    """Load a sample scene without coupling gameplay to project I/O."""
    return Scene.from_dict(json.loads(path.read_text(encoding="utf-8")))


class NeonArenaGame(RuntimeSystem):
    """Move a player, collect the target, and expose transient HUD state."""

    def __init__(
        self,
        runtime: Any,
        *,
        left_key: Any,
        right_key: Any,
        up_key: Any,
        down_key: Any,
        restart_key: Any,
        speed: float = 30.0,
        bounds: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 100.0),
    ) -> None:
        self.runtime = runtime
        self.left_key = left_key
        self.right_key = right_key
        self.up_key = up_key
        self.down_key = down_key
        self.restart_key = restart_key
        self.speed = speed
        self.bounds = bounds
        self.score = 0
        self.status = ""
        self._engine: Any = None

    @property
    def player(self) -> Any:
        return self._entity("player")

    @property
    def target(self) -> Any:
        return self._entity("target")

    @property
    def player_transform(self) -> TransformComponent:
        transform = self.player.get_component(TransformComponent)
        if transform is None:
            raise RuntimeError("Neon Arena player is missing a transform")
        return transform

    @property
    def target_transform(self) -> TransformComponent:
        transform = self.target.get_component(TransformComponent)
        if transform is None:
            raise RuntimeError("Neon Arena target is missing a transform")
        return transform

    def start(self, engine: Any) -> None:
        self._engine = engine
        self.score = 0
        self.status = ""

    def stop(self) -> None:
        self._engine = None
        self.score = 0
        self.status = ""

    def on_update(self, event: Update, signal: Any) -> None:
        if self.runtime.is_key_down(self.restart_key):
            self.restart()
            return
        if self.status == "won":
            return

        transform = self.player_transform
        dx = self._axis(self.right_key, self.left_key)
        dy = self._axis(self.down_key, self.up_key)
        min_x, min_y, max_x, max_y = self.bounds
        transform.x = max(min_x, min(max_x, transform.x + dx * self.speed * event.time_delta))
        transform.y = max(min_y, min(max_y, transform.y + dy * self.speed * event.time_delta))

        target = self.target
        target_transform = self.target_transform
        if target.enabled and abs(transform.x - target_transform.x) <= 1.0 and abs(transform.y - target_transform.y) <= 1.0:
            target.enabled = False
            self.score += 1
            self.status = "won"

    def restart(self) -> None:
        engine = self._engine
        if engine is None:
            return
        engine.stop()
        engine.play()

    def _axis(self, positive_key: Any, negative_key: Any) -> int:
        return int(self.runtime.is_key_down(positive_key)) - int(self.runtime.is_key_down(negative_key))

    def _entity(self, tag: str) -> Any:
        scene = self._engine.active_scene if self._engine is not None else None
        if scene is None:
            raise RuntimeError("Neon Arena is not running")
        entities = scene.get_entities_by_tag(tag)
        if not entities:
            raise RuntimeError(f"Neon Arena scene is missing a {tag} entity")
        return entities[0]
