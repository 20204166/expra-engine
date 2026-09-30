"""Window timer lifecycle: track, schedule, cancel and safely deliver QTimers.

Timers are addressed by string identifiers so the shared window logic can
schedule, cancel and drop them without touching Qt objects.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from typing import Any


class QtTimerDelivery:
    def __init__(
        self,
        *,
        is_closing: Callable[[], bool],
        logger: logging.Logger,
        on_interrupt: Callable[[], None] | None = None,
    ) -> None:
        self._is_closing = is_closing
        self._logger = logger
        self._on_interrupt = on_interrupt
        self._timers: dict[str, Any] = {}
        self._ids = itertools.count(1)

    @property
    def pending_ids(self) -> set[str]:
        return set(self._timers)

    def schedule(self, delay: int, callback: Callable[..., None], *args: object) -> str | None:
        if self._is_closing():
            return None
        from PySide6.QtCore import QTimer

        identifier = f"qt-timer-{next(self._ids)}"

        def run_callback() -> None:
            self._timers.pop(identifier, None)
            if not self._is_closing():
                try:
                    callback(*args)
                except KeyboardInterrupt:
                    if self._on_interrupt is not None and not self._is_closing():
                        self._on_interrupt()

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(run_callback)
        self._timers[identifier] = timer
        timer.start(max(0, int(delay)))
        return identifier

    def cancel(self, identifier: str | None) -> bool:
        if identifier is None:
            return True
        timer = self._timers.pop(identifier, None)
        if timer is not None:
            timer.stop()
        return True

    def cancel_all(self) -> None:
        for identifier in tuple(self._timers):
            self.cancel(identifier)


__all__ = ["QtTimerDelivery"]
