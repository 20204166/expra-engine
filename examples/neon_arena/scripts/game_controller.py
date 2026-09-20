"""Score, win, and restart rules for scripted Neon Arena."""

from __future__ import annotations

from typing import Any, cast

from expra_engine.runtime.behaviour import Behaviour, exposed

from .events import GameWon, RestartRequested, TargetCollected


class GameController(Behaviour):
    """Own the round state while other Behaviours own entity decisions."""

    target_score = exposed(1, min=1, tooltip="Targets required to win")

    def __init__(self) -> None:
        super().__init__()
        self.score = 0
        self.status = ""
        self.won_events = 0

    def on_start(self) -> None:
        self.score = 0
        self.status = ""
        self.won_events = 0

    def on_target_collected(self, event: TargetCollected, signal: object) -> None:
        del event
        self.score += 1
        if self.score >= cast(int, self.target_score):
            self.emit(GameWon())

    def on_game_won(self, event: GameWon, signal: object) -> None:
        del event, signal
        self.won_events += 1
        self.status = "won"

    def on_input(self, event: object, signal: object) -> bool:
        del signal
        if (
            getattr(getattr(event, "action", None), "value", None) == "restart"
            and getattr(event, "phase", None) == "pressed"
        ):
            self.emit(RestartRequested())
            return True
        return False

    def on_restart_requested(self, event: RestartRequested, signal: object) -> None:
        del event, signal
        engine = cast(Any, self.engine)
        if engine is not None:
            engine.stop()
            engine.play()
