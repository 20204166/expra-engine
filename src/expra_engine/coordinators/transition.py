"""Shared transition timing for status changes.

Copied from System Analyzer maintenance/ui/transition.py — domain-neutral,
no System Analyzer imports.

A ``PendingTransition`` applies one delayed state change at most once, and
starting a newer one always supersedes (cancels) any older pending change.
"""

from collections.abc import Callable
from typing import Any


class PendingTransition:
    """One cancellable, supersedable delayed state application.

    ``start(delay, apply)`` schedules ``apply`` after ``delay`` milliseconds,
    superseding any currently pending one. The callback verifies its
    generation so a queued timer that fires after cancellation is ignored.
    """

    def __init__(
        self,
        schedule: Callable[[int, Callable[[], None]], Any],
        cancel: Callable[[Any], bool],
    ) -> None:
        self._schedule = schedule
        self._cancel = cancel
        self._id: Any = None
        self._generation = 0

    @property
    def pending_id(self) -> Any:
        return self._id

    def start(self, delay: int, apply: Callable[[], None]) -> None:
        self._generation += 1
        generation = self._generation
        if self._id is not None:
            self._cancel(self._id)
            self._id = None
        fired = False
        callback = self._run(apply, generation)

        def run() -> None:
            nonlocal fired
            fired = True
            callback()

        identifier = self._schedule(delay, run)
        if not fired:
            self._id = identifier

    def cancel(self) -> None:
        if self._id is not None:
            self._cancel(self._id)
            self._id = None
            self._generation += 1

    def _run(self, apply: Callable[[], None], generation: int) -> Callable[[], None]:
        def run() -> None:
            if generation != self._generation:
                return
            self._id = None
            apply()

        return run
