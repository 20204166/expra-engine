"""Minimal public-API dogfood Behaviour for project scripts."""

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0, category="Movement")
    health = exposed(100, min=0, max=100, category="Combat")

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        if self.input.is_held("move_right"):
            transform.x += self.speed * dt

    def on_destroy(self) -> None:
        """Release script-owned references; engine services own teardown."""
