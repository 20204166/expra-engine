"""Fixed-timestep runtime clock.

Adapted from ppb/systems/clocks.py Updater (PursuedPyBear, Artistic
License 2.0).

Key preserved semantics:
  - Fixed-timestep accumulator: wall-clock time accumulates until a full
    step is due, then one (or more) Update events are emitted.
  - ``on_idle`` is the driver: each Idle event advances the accumulator.
  - Multiple Update events per Idle are possible when the wall clock
    outpaces the fixed step (catch-up without spiral-of-death).

Expra-specific differences:
  - RuntimeClock is a standalone class, not a System subclass (System
    abstraction comes in a later phase).
  - Default time_step is 1/60 (≈16.67 ms) rather than PPB's 0.016.
  - start() / stop() lifecycle replace __enter__/__exit__.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from expra_engine.runtime.events import Idle, Update

__all__ = ("RuntimeClock",)


class RuntimeClock:
    """Converts wall-clock Idle events into fixed-timestep Update events.

    Install by registering ``on_idle`` as an event handler on the scene
    root, or by calling ``tick(idle_event, signal)`` directly.

    Pause semantics
    ~~~~~~~~~~~~~~~
    When ``paused`` is True, scaled Update events are suppressed.  The
    unscaled accumulator continues advancing so pause menus and UI
    animations can use ``time_scale=0`` or ``clock="unscaled"`` in the
    Timeline without receiving a large spike on resume.

    Time scale
    ~~~~~~~~~~
    ``time_scale`` multiplies the effective Update ``time_delta``.  A scale
    of 0.5 produces slow-motion; 2.0 produces fast-forward.  Scale of 0.0
    suppresses scaled Updates without pausing unscaled consumers.

    Example::

        clock = RuntimeClock(time_step=1 / 60)
        # In your game-loop:
        clock.on_idle(Idle(wall_dt), event_queue.signal)
    """

    def __init__(self, time_step: float = 1.0 / 60.0, time_scale: float = 1.0) -> None:
        if time_step <= 0:
            raise ValueError(f"time_step must be positive, got {time_step!r}")
        if time_scale < 0.0:
            raise ValueError(f"time_scale must be non-negative, got {time_scale!r}")
        self.time_step = time_step
        self.time_scale = time_scale
        self._accumulated: float = 0.0
        self._paused: bool = False
        self._unscaled_elapsed: float = 0.0

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Pause scaled simulation updates without clearing the accumulator."""
        self._paused = True
        # Discard accumulated scaled time so resume doesn't spike.
        self._accumulated = 0.0

    def resume(self) -> None:
        """Resume scaled simulation updates cleanly (no dt spike)."""
        self._paused = False
        self._accumulated = 0.0

    @property
    def unscaled_elapsed(self) -> float:
        """Total unscaled real time processed since construction."""
        return self._unscaled_elapsed

    def reset(self) -> None:
        """Discard accumulated time (e.g. on stop)."""
        self._accumulated = 0.0
        self._unscaled_elapsed = 0.0
        self._paused = False

    def on_idle(self, event: Idle, signal: Callable[[Any], None]) -> None:
        """Respond to an Idle event by emitting Update events.

        Accumulates wall-clock time and emits one Update per full
        time_step.  This prevents the spiral-of-death: leftover fraction
        carries forward to the next idle instead of being dropped or
        causing extra steps.

        When paused or time_scale is 0, scaled updates are suppressed;
        the unscaled elapsed counter still advances.
        """
        self._unscaled_elapsed += event.time_delta
        if self._paused or self.time_scale == 0.0:
            return
        effective_delta = event.time_delta * self.time_scale
        self._accumulated += effective_delta
        while self._accumulated >= self.time_step:
            self._accumulated -= self.time_step
            signal(Update(self.time_step))
