"""Runtime-only gameplay behaviour contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from expra_engine.runtime.events import Update
from expra_engine.runtime.input import ActionEvent

if TYPE_CHECKING:
    from expra_engine.core.entity import Entity

Signal = Callable[[object], None]


class Behaviour:
    """Base class for an object-owned runtime gameplay behaviour."""

    def __init__(self) -> None:
        self.entity: Entity | None = None
        self.enabled = True

    def on_attach(self, entity: Entity) -> None:
        """Handle attachment to an entity."""

    def on_start(self) -> None:
        """Handle the start of runtime execution."""

    def on_update(self, event: Update, signal: Signal) -> None:
        """Handle a runtime update event."""

    def on_input(self, event: ActionEvent, signal: Signal) -> bool:
        """Handle an action event and return whether it was consumed."""
        return False

    def on_stop(self) -> None:
        """Handle the end of runtime execution."""

    def on_detach(self) -> None:
        """Handle detachment from an entity."""


BehaviourFactory = Callable[[], Behaviour]


__all__ = ["Behaviour", "BehaviourFactory", "Signal"]
