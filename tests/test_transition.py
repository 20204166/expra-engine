"""Tests for PendingTransition."""

import unittest
from typing import Any

from expra_engine.coordinators.transition import PendingTransition
from tests.support.scheduling import FakeScheduler


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

    def test_callback_is_applied_at_most_once(self) -> None:
        callbacks: list[Any] = []
        applied: list[str] = []

        def schedule(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            return len(callbacks)

        t = PendingTransition(schedule, lambda _identifier: True)
        t.start(100, lambda: applied.append("applied"))

        callbacks[0]()
        callbacks[0]()

        self.assertEqual(applied, ["applied"])

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

    def test_cancel_invalidates_before_cancel_hook_runs(self) -> None:
        applied: list[str] = []
        callbacks: list[Any] = []

        def schedule(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            return 1

        def cancel(_identifier: Any) -> bool:
            callbacks[0]()
            return True

        t = PendingTransition(schedule, cancel)
        t.start(100, lambda: applied.append("applied"))
        t.cancel()

        self.assertEqual(applied, [])

    def test_cancel_failure_leaves_transition_invalidated(self) -> None:
        applied: list[str] = []
        callbacks: list[Any] = []

        def schedule(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            return 1

        def cancel(_identifier: Any) -> bool:
            raise RuntimeError("event loop is not running")

        t = PendingTransition(schedule, cancel)
        t.start(100, lambda: applied.append("applied"))
        with self.assertRaises(RuntimeError):
            t.cancel()

        callbacks[0]()
        self.assertEqual(applied, [])
        self.assertIsNone(t.pending_id)

    def test_supersede_failure_does_not_leave_old_pending_id(self) -> None:
        callbacks: list[Any] = []

        def schedule(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            return len(callbacks)

        def cancel(_identifier: Any) -> bool:
            raise RuntimeError("event loop is not running")

        t = PendingTransition(schedule, cancel)
        t.start(100, lambda: None)
        with self.assertRaises(RuntimeError):
            t.start(100, lambda: None)

        self.assertIsNone(t.pending_id)

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

    def test_synchronous_scheduler_does_not_leave_stale_pending_id(self) -> None:
        applied: list[str] = []

        def schedule(_delay: int, callback: Any) -> int:
            callback()
            return 1

        t = PendingTransition(schedule, lambda _identifier: True)
        t.start(0, lambda: applied.append("applied"))
        self.assertEqual(applied, ["applied"])
        self.assertIsNone(t.pending_id)

    def test_schedule_failure_invalidates_callback_registered_before_error(self) -> None:
        callbacks: list[Any] = []
        applied: list[str] = []

        def register_then_fail(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            raise RuntimeError("timer backend failed after registration")

        transition = PendingTransition(register_then_fail, lambda _identifier: True)
        with self.assertRaisesRegex(RuntimeError, "after registration"):
            transition.start(100, lambda: applied.append("applied"))

        callbacks[0]()

        self.assertEqual(applied, [])
        self.assertIsNone(transition.pending_id)


if __name__ == "__main__":
    unittest.main()
