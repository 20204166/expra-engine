"""Tests for PendingTransition."""

import unittest
from typing import Any

from expra_engine.coordinators.transition import PendingTransition


class FakeScheduler:
    """Records scheduled callbacks with their delays."""

    def __init__(self) -> None:
        self._scheduled: list[tuple[int, Any]] = []
        self._cancelled: list[Any] = []
        self._next_id = 0

    def schedule(self, delay: int, callback: Any) -> int:
        self._next_id += 1
        self._scheduled.append((delay, callback))
        return self._next_id

    def cancel(self, identifier: Any) -> bool:
        self._cancelled.append(identifier)
        return True

    def fire_last(self) -> None:
        if self._scheduled:
            _, callback = self._scheduled[-1]
            callback()


class TestPendingTransition(unittest.TestCase):
    def test_start_schedules_callback(self) -> None:
        fake = FakeScheduler()
        t = PendingTransition(fake.schedule, fake.cancel)
        applied: list[str] = []
        t.start(100, lambda: applied.append("applied"))
        fake.fire_last()
        self.assertEqual(applied, ["applied"])

    def test_supersede_cancels_previous(self) -> None:
        fake = FakeScheduler()
        t = PendingTransition(fake.schedule, fake.cancel)
        applied: list[str] = []
        t.start(100, lambda: applied.append("first"))
        t.start(100, lambda: applied.append("second"))
        self.assertIn(1, fake._cancelled)

    def test_superseded_callback_does_not_fire(self) -> None:
        applied: list[str] = []
        callbacks: list[Any] = []

        def schedule(delay: int, cb: Any) -> int:
            callbacks.append(cb)
            return len(callbacks)

        def cancel(identifier: Any) -> bool:
            return True

        t = PendingTransition(schedule, cancel)
        t.start(100, lambda: applied.append("first"))
        first_cb = callbacks[-1]
        t.start(100, lambda: applied.append("second"))
        first_cb()  # fires the old callback
        self.assertNotIn("first", applied)

    def test_cancel_prevents_fire(self) -> None:
        applied: list[str] = []
        callbacks: list[Any] = []

        def schedule(delay: int, cb: Any) -> int:
            callbacks.append(cb)
            return len(callbacks)

        def cancel(identifier: Any) -> bool:
            return True

        t = PendingTransition(schedule, cancel)
        t.start(100, lambda: applied.append("x"))
        t.cancel()
        if callbacks:
            callbacks[-1]()
        self.assertEqual(applied, [])

    def test_cancel_when_nothing_pending_safe(self) -> None:
        fake = FakeScheduler()
        t = PendingTransition(fake.schedule, fake.cancel)
        t.cancel()  # Should not raise

    def test_pending_id_set_after_start(self) -> None:
        fake = FakeScheduler()
        t = PendingTransition(fake.schedule, fake.cancel)
        self.assertIsNone(t.pending_id)
        t.start(50, lambda: None)
        self.assertIsNotNone(t.pending_id)


if __name__ == "__main__":
    unittest.main()
