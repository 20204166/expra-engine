"""Thread-safe Tk delivery queue.

Worker threads enqueue callbacks via __call__; the Tk main thread drains
them every 25 ms via a scheduled poll.  This is the ONLY correct way to
cross the thread boundary — never call widget.after_idle() or
widget.configure() from a worker thread directly.

Adapted from System Analyzer maintenance/components/background.py.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from queue import Empty, Queue


class TkDeliveryQueue:
    """Queue-backed, Tk-thread delivery mechanism.

    Use as the ``deliver=`` argument to AppCoordinator.  Worker threads call
    ``queue(callback)`` (or the queue itself, since it is callable); the Tk
    main thread drains the queue every 25 ms.
    """

    def __init__(self, widget: tk.Misc) -> None:
        self._widget = widget
        self._callbacks: Queue[Callable[[], None]] = Queue()
        self._closed = False
        self._after_id: str | None = None
        try:
            widget.bind("<Destroy>", self._on_destroy, add="+")
            self._after_id = widget.after(0, self._drain)
        except (RuntimeError, tk.TclError):
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __call__(self, callback: Callable[[], None]) -> None:
        """Enqueue a callback for delivery on the Tk main thread (thread-safe)."""
        if not self._closed:
            self._callbacks.put(callback)

    def close(self) -> None:
        """Stop accepting callbacks and cancel the drain loop."""
        self._close()

    @property
    def is_closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_destroy(self, event: object = None) -> None:
        if event is not None and getattr(event, "widget", self._widget) is not self._widget:
            return
        self._close()

    def _close(self) -> None:
        self._closed = True
        after_id = self._after_id
        self._after_id = None
        if after_id is not None:
            with contextlib.suppress(RuntimeError, tk.TclError):
                self._widget.after_cancel(after_id)
        while True:
            try:
                self._callbacks.get_nowait()
            except Empty:
                break

    def _drain(self) -> None:
        self._after_id = None
        if self._closed:
            return
        try:
            if not self._widget.winfo_exists():
                self._close()
                return
        except (RuntimeError, tk.TclError):
            self._close()
            return
        while True:
            try:
                callback = self._callbacks.get_nowait()
            except Empty:
                break
            with contextlib.suppress(RuntimeError, tk.TclError):
                callback()
        try:
            self._after_id = self._widget.after(25, self._drain)
        except (RuntimeError, tk.TclError):
            self._closed = True
