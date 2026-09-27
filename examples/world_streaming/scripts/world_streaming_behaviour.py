"""PlayerBehaviour for the world_streaming example.

Two levels (town and cave) connected by FADE transitions. The player moves
left/right; reaching either edge triggers travel to the neighbouring level.
"""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    speed = exposed(8.0, min=1.0, max=30.0, step=0.5, category="Player")
    travel_edge = exposed(8.5, min=2.0, max=20.0, step=0.5, category="Player")

    # connection_id exposed so the inspector can see which connection to use
    connection_id = exposed("", category="Player")

    def __init__(self) -> None:
        super().__init__()
        self._travelling = False

    def on_start(self) -> None:
        self._travelling = False

    def on_update(self, dt: Any, signal: Any = None) -> None:
        dt = max(0.0, float(dt))
        transform = self.get_component(TransformComponent)
        if transform is None:
            return

        dx = float(
            self.input.is_held("move_right") or self.input.is_held("move_right_alt")
        ) - float(self.input.is_held("move_left") or self.input.is_held("move_left_alt"))
        transform.x += dx * float(self.speed) * dt

        if self._travelling or not self.connection_id:
            return

        edge = float(self.travel_edge)
        wss = getattr(self.engine, "world_streaming_system", None)
        if wss is None:
            return

        if transform.x > edge or transform.x < -edge:
            self._travelling = True
            wss.travel(str(self.connection_id))
