"""RuntimeSystem — pluggable game-runtime subsystem protocol.

Conceptually adapted from ppb/systemslib.py (PursuedPyBear, Artistic
License 2.0). PPB's System inherits from GameObject and uses
__enter__/__exit__ for lifecycle. Expra's RuntimeSystem is a plain
Protocol/base class with explicit lifecycle methods instead.

This keeps the Engine clean: game features (physics, renderer, audio)
attach as RuntimeSystems rather than growing the Engine class.

Usage::

    class PhysicsSystem(RuntimeSystem):
        def start(self, engine: Engine) -> None:
            ...
        def stop(self) -> None:
            ...
        def on_update(self, event: Update, signal) -> None:
            ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expra_engine.core.engine import Engine

__all__ = ("RuntimeSystem",)


class RuntimeSystem:
    """Base class for pluggable runtime subsystems.

    Subclass and override the methods you need. All methods are no-ops
    by default so minimal systems only implement what they require.

    Lifecycle:
        1. ``start(engine)``  — called when the engine enters PLAY state.
        2. ``on_idle / on_update / ...`` — called via event dispatch.
        3. ``stop()``         — called when the engine leaves PLAY state.
    """

    def start(self, engine: Engine) -> None:
        """Called when the engine enters PLAY state.

        :param engine: The engine that owns this system.
        """

    def stop(self) -> None:
        """Called when the engine leaves PLAY/PAUSED and returns to EDIT."""
