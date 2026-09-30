"""Thread-safe Qt delivery queue.

Worker threads enqueue callbacks via __call__; the Qt main thread drains
them every 25 ms via a QTimer.  This is the ONLY correct way to cross the
thread boundary — never call widget methods from a worker thread directly.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any

_MAX_CALLBACKS_PER_DRAIN = 100
_MAX_DRAIN_DURATION_SECONDS = 0.005


class QtDeliveryQueue:
    """Queue-backed, Qt-main-thread delivery mechanism.

    Use as the ``deliver=`` argument to AppCoordinator.  Worker threads call
    the queue (it is callable); the Qt main thread drains it every 25 ms via
    a singleShot QTimer.

    ``widget`` must be a QObject whose ``destroyed`` signal is accessible so
    the queue can stop itself when the window is closed.
    """

    def __init__(self, widget: Any) -> None:
        self._callbacks: Queue[Callable[[], None]] = Queue()
        self._state_lock = threading.RLock()
        self._closed = False
        self._timer: Any = None  # QTimer | None, held on main thread
        from PySide6.QtCore import QThread

        self._owner_thread = QThread.currentThread()
        try:
            widget.destroyed.connect(self._on_destroyed)
            self._reschedule()
        except RuntimeError:
            self._close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __call__(self, callback: Callable[[], None]) -> None:
        """Enqueue a callback for delivery on the Qt main thread (thread-safe)."""
        with self._state_lock:
            if not self._closed:
                self._callbacks.put(callback)

    def close(self) -> None:
        """Mark as closed; the drain loop stops on the next tick."""
        self._close()

    @property
    def is_closed(self) -> bool:
        with self._state_lock:
            return self._closed

    # ------------------------------------------------------------------
    # Internal — all timer operations run on the Qt main thread
    # ------------------------------------------------------------------

    def _on_destroyed(self, *args: object) -> None:
        """Called on the Qt main thread when the parent widget is destroyed."""
        self._close()

    def _close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        while True:
            try:
                self._callbacks.get_nowait()
            except Empty:
                break
        # A QTimer may only be stopped -- and its last reference only dropped --
        # on the thread that owns it. From any other thread just leave it: its
        # next fire sees ``_closed`` on the owner thread, stops rescheduling, and
        # releases it there.
        from PySide6.QtCore import QThread

        if QThread.currentThread() == self._owner_thread:
            with self._state_lock:
                timer = self._timer
                self._timer = None
            if timer is not None:
                with contextlib.suppress(RuntimeError):
                    timer.stop()

    def _reschedule(self) -> None:
        """Create and arm a new singleShot QTimer (must run on main thread)."""
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self._drain)
        with self._state_lock:
            if self._closed:
                return
            self._timer = timer
        timer.start(25)

    def _drain(self) -> None:
        """Called on the Qt main thread by the QTimer."""
        with self._state_lock:
            self._timer = None
            if self._closed:
                return
        drain_started = time.monotonic()
        delivered = 0
        while delivered < _MAX_CALLBACKS_PER_DRAIN:
            if delivered and time.monotonic() - drain_started >= _MAX_DRAIN_DURATION_SECONDS:
                break
            try:
                callback = self._callbacks.get_nowait()
            except Empty:
                break
            delivered += 1
            with contextlib.suppress(Exception):
                callback()
        with self._state_lock:
            if self._closed:
                return
        self._reschedule()


__all__ = ["QtDeliveryQueue"]
