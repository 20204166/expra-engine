"""Tests for TkDeliveryQueue — thread-safe Tk callback delivery.

TkDeliveryQueue requires a Tk widget; these tests use a FakeWidget that
records after/after_cancel calls so no display is needed.
"""

import threading
import tkinter as tk
import unittest
from collections.abc import Callable
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

if TYPE_CHECKING:
    from expra_engine.editor.delivery import TkDeliveryQueue


class FakeWidget:
    """Minimal fake Tk widget for testing TkDeliveryQueue without a display."""

    def __init__(self) -> None:
        self.after_calls: list[tuple[int, Callable[[], None]]] = []
        self.cancelled: list[str] = []
        self.exists = True
        self._counter = 0
        self._destroy_callbacks: list[Callable[..., None]] = []

    def after(self, delay: int, callback: Callable[[], None]) -> str:
        self.after_calls.append((delay, callback))
        self._counter += 1
        return f"after#{self._counter}"

    def after_cancel(self, identifier: str) -> None:
        self.cancelled.append(identifier)

    def bind(self, event: str, callback: Callable[..., None], add: str = "") -> None:
        if event == "<Destroy>":
            self._destroy_callbacks.append(callback)

    def winfo_exists(self) -> bool:
        return self.exists

    def fire_destroy(self) -> None:
        mock_event = Mock()
        mock_event.widget = self
        for cb in self._destroy_callbacks:
            cb(mock_event)


class TkDeliveryQueueTests(unittest.TestCase):
    def _make_queue(self) -> tuple["TkDeliveryQueue", FakeWidget]:
        from expra_engine.editor.delivery import TkDeliveryQueue

        widget = FakeWidget()
        q = TkDeliveryQueue(cast(tk.Misc, widget))
        # pop the initial after(0, _drain) call
        widget.after_calls.clear()
        return q, widget

    def test_callable_enqueues_callback_without_executing(self) -> None:
        q, _widget = self._make_queue()
        called: list[str] = []

        q(lambda: called.append("fired"))

        self.assertEqual(called, [], "callback must not execute on enqueue")

    def test_drain_executes_callbacks_from_queue(self) -> None:
        q, _widget = self._make_queue()
        called: list[str] = []
        q(lambda: called.append("a"))
        q(lambda: called.append("b"))

        # Manually invoke _drain (simulates Tk calling it on main thread)
        q._drain()  # type: ignore[attr-defined]

        self.assertEqual(called, ["a", "b"])

    def test_closed_queue_rejects_new_callbacks(self) -> None:
        q, _widget = self._make_queue()
        called: list[str] = []

        q.close()
        q(lambda: called.append("should not fire"))

        q._drain()  # type: ignore[attr-defined]
        self.assertEqual(called, [])

    def test_is_closed_property(self) -> None:
        q, _widget = self._make_queue()
        self.assertFalse(q.is_closed)
        q.close()
        self.assertTrue(q.is_closed)

    def test_close_discards_pending_callbacks_safely(self) -> None:
        q, _widget = self._make_queue()
        q(lambda: None)
        q(lambda: None)

        q.close()  # must not raise; pending callbacks discarded

        self.assertTrue(q.is_closed)

    def test_destroy_event_closes_queue(self) -> None:
        q, widget = self._make_queue()
        self.assertFalse(q.is_closed)

        widget.fire_destroy()

        self.assertTrue(q.is_closed)

    def test_drain_reschedules_itself(self) -> None:
        q, widget = self._make_queue()
        q._drain()  # type: ignore[attr-defined]

        # After drain, a new after(25, _drain) must have been scheduled
        self.assertEqual(len(widget.after_calls), 1)
        delay, _ = widget.after_calls[0]
        self.assertEqual(delay, 25)

    def test_drain_stops_when_widget_destroyed(self) -> None:
        q, widget = self._make_queue()
        widget.exists = False

        q._drain()  # type: ignore[attr-defined]

        self.assertTrue(q.is_closed)
        self.assertEqual(widget.after_calls, [], "must not reschedule after widget gone")

    def test_queue_is_thread_safe_put_from_thread(self) -> None:
        q, _widget = self._make_queue()
        results: list[int] = []
        errors: list[Exception] = []

        def enqueue() -> None:
            try:
                for i in range(50):

                    def callback(i: int = i) -> None:
                        results.append(i)

                    q(callback)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=enqueue) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        q._drain()  # type: ignore[attr-defined]

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 200)

    def test_close_is_idempotent(self) -> None:
        q, _widget = self._make_queue()
        q.close()
        q.close()  # must not raise
        self.assertTrue(q.is_closed)


if __name__ == "__main__":
    unittest.main()
