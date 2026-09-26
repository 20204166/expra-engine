"""Per-component refresh scheduling — SCHEDULER DECIDES WHEN.

Adapted from System Analyzer maintenance/components/coordinator.py
(ComponentRefreshScheduler).

Domain-specific interval names (cpu, gpu, memory, …) replaced with generic
intervals dict so the engine can name its own components.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from expra_engine.observability import ObservabilityWatcher


def _finite_time(value: float) -> float:
    resolved = float(value)
    if not isfinite(resolved):
        raise ValueError("time must be finite")
    return resolved


def _make_monotonic_clock(clock: Callable[[], float]) -> Callable[[], float]:
    last = float("-inf")

    def read() -> float:
        nonlocal last
        current = _finite_time(clock())
        if current < last:
            return last
        last = current
        return current

    return read


@dataclass(slots=True)
class _RefreshEntry:
    interval: float
    next_due: float = 0.0
    in_flight: bool = False
    paused: bool = False
    refresh_requested: bool = False
    last_success: float | None = None
    last_error: tuple[str, str] | None = None


class ComponentRefreshScheduler:
    """Track per-component refresh due times and prevent overlapping runs.

    ``intervals`` is a ``{key: milliseconds}`` dict. Keys are caller-defined
    strings — the engine may use "hierarchy", "inspector", "assets", "console",
    "viewport", or any other component name.

    SCHEDULER DECIDES WHEN. The application layer calls ``begin`` before
    starting work and ``finish`` when it completes; the scheduler tracks
    in-flight state so concurrent runs of the same key are coalesced.
    """

    def __init__(
        self,
        intervals: dict[str, int],
        *,
        clock: Callable[[], float] | None = None,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        for milliseconds in intervals.values():
            self._validate_interval(milliseconds)
        self.intervals = dict(intervals)
        self._clock = _make_monotonic_clock(clock or time.monotonic)
        self._observer = observer or ObservabilityWatcher()
        self._records = {
            key: _RefreshEntry(interval=milliseconds / 1000.0)
            for key, milliseconds in self.intervals.items()
        }

    def begin(self, key: str, now: float) -> bool:
        now = _finite_time(now)
        entry = self._records.get(key)
        if entry is None:
            entry = _RefreshEntry(interval=5.0)
            self._records[key] = entry
        if entry.in_flight or entry.paused:
            if entry.in_flight:
                with contextlib.suppress(Exception):
                    self._observer.record_event(f"component:{key}", "coalesced")
            return False
        if not self._is_due(entry, now):
            return False
        entry.in_flight = True
        entry.refresh_requested = False
        if now >= entry.next_due:
            periods = int((now - entry.next_due) // entry.interval) + 1
            entry.next_due += periods * entry.interval
            if entry.next_due <= now:
                entry.next_due = now + entry.interval
        else:
            entry.next_due = now + entry.interval
        return True

    def finish(self, key: str) -> None:
        entry = self._records.get(key)
        if entry is None:
            return
        entry.in_flight = False

    def record_success(self, key: str, completed_at: float) -> None:
        entry = self._entry(key)
        entry.last_success = _finite_time(completed_at)
        entry.last_error = None

    def record_error(self, key: str, category: str, detail: str) -> None:
        self._entry(key).last_error = (category, detail[:160])

    def diagnostic_state(self, key: str) -> tuple[bool, bool, float | None, tuple[str, str] | None]:
        entry = self._entry(key)
        return entry.in_flight, entry.paused, entry.last_success, entry.last_error

    def cancel(self, key: str) -> None:
        entry = self._configured_entry(key)
        entry.in_flight = False
        entry.refresh_requested = False

    def mark_all_refreshed(self, now: float) -> None:
        now = _finite_time(now)
        for entry in self._records.values():
            entry.next_due = now + entry.interval
            entry.refresh_requested = False

    def due_keys(self, now: float) -> tuple[str, ...]:
        now = _finite_time(now)
        return tuple(key for key, entry in self._records.items() if self._is_due(entry, now))

    def collect_due(self, now: float | None = None) -> tuple[str, ...]:
        resolved_now = self._clock() if now is None else now
        return self.due_keys(resolved_now)

    def next_deadline(self, now: float | None = None) -> float | None:
        resolved_now = _finite_time(self._clock() if now is None else now)
        deadlines: list[float] = []
        for entry in self._records.values():
            ready_at = self._ready_at(entry, resolved_now)
            if ready_at is not None:
                deadlines.append(ready_at)
        return min(deadlines) if deadlines else None

    def in_flight(self, key: str) -> bool:
        return self._entry(key).in_flight

    def has_pending_work(self) -> bool:
        return any(entry.in_flight or entry.refresh_requested for entry in self._records.values())

    def set_interval(self, key: str, milliseconds: int, now: float) -> None:
        now = _finite_time(now)
        entry = self._configured_entry(key)
        self._validate_interval(milliseconds)
        self.intervals[key] = milliseconds
        entry.interval = milliseconds / 1000.0
        entry.next_due = now + entry.interval

    def pause(self, key: str) -> None:
        self._configured_entry(key).paused = True

    def resume(self, key: str) -> None:
        self._configured_entry(key).paused = False

    def is_paused(self, key: str) -> bool:
        return self._entry(key).paused

    def request_refresh(self, key: str) -> None:
        self._configured_entry(key).refresh_requested = True

    @staticmethod
    def _validate_interval(milliseconds: int) -> None:
        if not isinstance(milliseconds, int) or isinstance(milliseconds, bool):
            raise TypeError("Interval must be an integer number of milliseconds")
        if milliseconds <= 0:
            raise ValueError("Interval must be positive")

    def _configured_entry(self, key: str) -> _RefreshEntry:
        if key not in self.intervals:
            raise ValueError(f"Unknown component: {key}")
        return self._entry(key)

    def _entry(self, key: str) -> _RefreshEntry:
        try:
            return self._records[key]
        except KeyError as error:
            raise ValueError(f"Unknown component: {key}") from error

    @staticmethod
    def _ready_at(entry: _RefreshEntry, now: float) -> float | None:
        if entry.paused or entry.in_flight:
            return None
        ready_at = entry.next_due
        if entry.refresh_requested:
            ready_at = min(ready_at, now)
        return ready_at

    def _is_due(self, entry: _RefreshEntry, now: float) -> bool:
        ready_at = self._ready_at(entry, now)
        return ready_at is not None and ready_at <= now
