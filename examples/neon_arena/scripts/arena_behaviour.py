"""Target interaction for the scripted Neon Arena mode."""

from __future__ import annotations

from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour

from .events import TargetCollected


class ArenaBehaviour(Behaviour):
    """Detect the existing target interaction and publish one collection event."""

    def on_update(self, dt: float) -> None:
        del dt
        if self.entity is None or not self.entity.enabled:
            return
        scene = cast(Any, self.scene)
        if scene is None:
            return
        players = scene.get_entities_by_tag("player")
        targets = scene.get_entities_by_tag("target")
        if not players or not targets or not targets[0].enabled:
            return
        player_transform = players[0].get_component(TransformComponent)
        target_transform = targets[0].get_component(TransformComponent)
        if player_transform is None or target_transform is None:
            return
        if (
            abs(player_transform.x - target_transform.x) <= 1.0
            and abs(player_transform.y - target_transform.y) <= 1.0
        ):
            targets[0].enabled = False
            self.emit(TargetCollected())
