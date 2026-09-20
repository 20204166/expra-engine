"""Deterministic, renderer-neutral runtime timelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from expra_engine.runtime.events import Update
from expra_engine.runtime.system import RuntimeSystem

__all__ = ("Timeline", "TimelineHandle")

ProgressCallback = Callable[[float], None]
CompleteCallback = Callable[[], None]
UnscaledDelta = Callable[[Update], float]


@dataclass
class _Entry:
    identifier: int
    delay: float
    duration: float
    on_update: ProgressCallback | None
    on_complete: CompleteCallback | None
    loop: bool
    clock: str
    elapsed: float = 0.0
    delay_elapsed: float = 0.0
    cancelled: bool = False


class TimelineHandle:
    """A reference to one scheduled timeline entry."""

    def __init__(self, timeline: Timeline, identifier: int) -> None:
        self._timeline = timeline
        self._identifier = identifier

    def cancel(self) -> bool:
        """Cancel this entry, returning whether it was still pending."""
        return self._timeline._cancel(self._identifier)


class Timeline(RuntimeSystem):
    """Advance callbacks from existing ``Update`` events.

    ``unscaled_delta`` is injectable because ``Update`` intentionally carries
    only the existing scaled time step.  Without a provider, unscaled entries
    receive the same delta as scaled entries.
    """

    def __init__(self, unscaled_delta: UnscaledDelta | None = None) -> None:
        self._entries: list[_Entry] = []
        self._next_identifier = 0
        self._paused = False
        self._last_progress = 0.0
        self._unscaled_delta = unscaled_delta

    @property
    def active(self) -> bool:
        return bool(self._entries)

    @property
    def progress(self) -> float:
        return self._last_progress

    def schedule(
        self,
        *,
        delay: float = 0.0,
        duration: float = 0.0,
        on_update: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
        loop: bool = False,
        clock: str = "scaled",
    ) -> TimelineHandle:
        """Schedule one delay/interpolation/completion sequence."""
        if not isfinite(delay) or delay < 0.0:
            raise ValueError("delay must be finite and non-negative")
        if not isfinite(duration) or duration < 0.0:
            raise ValueError("duration must be finite and non-negative")
        if clock not in {"scaled", "unscaled"}:
            raise ValueError("clock must be 'scaled' or 'unscaled'")

        self._next_identifier += 1
        entry = _Entry(
            self._next_identifier,
            delay,
            duration,
            on_update,
            on_complete,
            loop,
            clock,
        )
        self._entries.append(entry)
        return TimelineHandle(self, entry.identifier)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def on_update(self, event: Update, signal: object) -> None:
        del signal
        unscaled = self._unscaled_delta(event) if self._unscaled_delta else event.time_delta
        self.advance(event.time_delta, unscaled_delta=unscaled)

    def advance(self, scaled_delta: float, *, unscaled_delta: float | None = None) -> None:
        """Advance pending entries by injected scaled and unscaled deltas."""
        if not isfinite(scaled_delta) or (
            unscaled_delta is not None and not isfinite(unscaled_delta)
        ):
            raise ValueError("timeline deltas must be finite and non-negative")
        if scaled_delta < 0.0 or (unscaled_delta is not None and unscaled_delta < 0.0):
            raise ValueError("timeline deltas must be finite and non-negative")
        if self._paused:
            return
        actual_unscaled = scaled_delta if unscaled_delta is None else unscaled_delta
        for entry in list(self._entries):
            if entry.cancelled:
                continue
            delta = scaled_delta if entry.clock == "scaled" else actual_unscaled
            self._advance_entry(entry, delta)
        self._entries = [entry for entry in self._entries if not entry.cancelled]

    def stop(self) -> None:
        """Cancel all pending work when the owning runtime stops."""
        self._entries.clear()
        self._paused = False
        self._last_progress = 0.0

    def _cancel(self, identifier: int) -> bool:
        for entry in self._entries:
            if entry.identifier == identifier and not entry.cancelled:
                entry.cancelled = True
                return True
        return False

    def _advance_entry(self, entry: _Entry, delta: float) -> None:
        if entry.delay_elapsed < entry.delay:
            delay_remaining = entry.delay - entry.delay_elapsed
            if delta < delay_remaining:
                entry.delay_elapsed += delta
                return
            delta -= delay_remaining
            entry.delay_elapsed = entry.delay
            self._emit_update(entry, 0.0)

        if entry.duration == 0.0:
            self._emit_update(entry, 1.0)
            self._complete(entry)
            return

        while not entry.cancelled and delta >= entry.duration - entry.elapsed:
            delta -= entry.duration - entry.elapsed
            entry.elapsed = entry.duration
            self._emit_update(entry, 1.0)
            self._complete(entry)
            if not entry.loop or entry.cancelled:
                return
            entry.elapsed = 0.0
            entry.delay_elapsed = entry.delay

        if not entry.cancelled and delta > 0.0:
            entry.elapsed += delta
            self._emit_update(entry, entry.elapsed / entry.duration)

    def _emit_update(self, entry: _Entry, progress: float) -> None:
        self._last_progress = progress
        if entry.on_update is not None:
            entry.on_update(progress)

    def _complete(self, entry: _Entry) -> None:
        if entry.cancelled:
            return
        if entry.on_complete is not None:
            entry.on_complete()
        if not entry.loop:
            entry.cancelled = True
