"""Tk timer lifecycle support for the editor window.

Copied from System Analyzer maintenance/ui/window_supports/timer_delivery.py
— domain-neutral, no System Analyzer imports.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from typing import Any


def deadline_delay_ms(deadline: float, now: float) -> int:
    """Convert a monotonic deadline into a non-negative Tk delay."""
    return max(0, int((deadline - now) * 1000))


class TimerDelivery:
    """Track, schedule, cancel, and safely deliver window timers."""

    def __init__(
        self,
        *,
        master: Any,
        is_closing: Callable[[], bool],
        pending_ids: set[str],
        logger: logging.Logger,
        on_interrupt: Callable[[], None] | None = None,
    ) -> None:
        self._master = master
        self._is_closing = is_closing
        self._pending_ids = pending_ids
        self._logger = logger
        self._on_interrupt = on_interrupt

    def schedule(
        self,
        delay: int,
        callback: Callable[..., None],
        *args: object,
    ) -> str | None:
        if self._is_closing():
            return None

        identifier: str | None = None

        def run_callback() -> None:
            if identifier is not None:
                self._pending_ids.discard(identifier)
            if not self._is_closing():
                try:
                    callback(*args)
                except KeyboardInterrupt:
                    if self._on_interrupt is not None and not self._is_closing():
                        self._on_interrupt()

        try:
            identifier = self._master.after(delay, run_callback)
        except (RuntimeError, tk.TclError):
            if not self._is_closing():
                self._logger.exception("Failed to schedule Tkinter work")
            return None

        assert identifier is not None
        self._pending_ids.add(identifier)
        return identifier

    def cancel(self, identifier: str | None) -> bool:
        if identifier is None:
            return True
        try:
            self._master.after_cancel(identifier)
        except (RuntimeError, tk.TclError):
            if not self._is_closing():
                self._logger.exception("Failed to cancel Tkinter work")
            else:
                self._pending_ids.discard(identifier)
            return False
        self._pending_ids.discard(identifier)
        return True

    def cancel_all(self) -> None:
        for identifier in tuple(self._pending_ids):
            self.cancel(identifier)

    @staticmethod
    def invoke(callback: Callable[[], None], logger: logging.Logger) -> None:
        try:
            callback()
        except Exception as error:  # noqa: BLE001
            logger.warning("Dropped UI delivery callback: %s", error)
