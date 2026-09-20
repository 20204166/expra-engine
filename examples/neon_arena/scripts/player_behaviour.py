"""Player movement for the scripted Neon Arena mode."""

from __future__ import annotations

from typing import cast

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    """Consume semantic movement actions and update the player transform."""

    speed = exposed(30.0, min=0.0, tooltip="Player movement units per second")

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        dx = int(self.input.is_held("move_right")) - int(self.input.is_held("move_left"))
        dy = int(self.input.is_held("move_down")) - int(self.input.is_held("move_up"))
        speed = cast(float, self.speed)
        transform.x = max(0.0, min(100.0, transform.x + dx * speed * dt))
        transform.y = max(0.0, min(100.0, transform.y + dy * speed * dt))
