"""Tests for ComponentRefreshScheduler.

Adapted from System Analyzer tests/test_components.py (ComponentRefreshScheduler) —
behavior preserved: interval tracking, coalescing, pause/resume, due detection.
"""

import unittest

from expra_engine.coordinators.refresh_scheduler import ComponentRefreshScheduler
from tests.support.scheduling import FakeClock


def make_scheduler(intervals: dict[str, int] | None = None) -> tuple[ComponentRefreshScheduler, FakeClock]:
    clock = FakeClock(0.0)
    sched = ComponentRefreshScheduler(
        intervals or {"hierarchy": 1000, "inspector": 500},
        clock=clock,
    )
    return sched, clock


class TestComponentRefreshSchedulerBasics(unittest.TestCase):
    def test_component_due_after_interval(self) -> None:
        sched, clock = make_scheduler({"hierarchy": 1000})
        clock.advance(1.1)
        self.assertIn("hierarchy", sched.collect_due())

    def test_component_not_due_before_interval(self) -> None:
        # After begin+finish at t=0, next_due is set to 1.0 (0+interval).
        # At t=0.5 it should NOT be due yet.
        sched, clock = make_scheduler({"hierarchy": 1000})
        self.assertTrue(sched.begin("hierarchy", clock()))  # claims initial due slot
        sched.finish("hierarchy")
        clock.advance(0.5)
        self.assertNotIn("hierarchy", sched.collect_due())

    def test_begin_marks_in_flight(self) -> None:
        sched, clock = make_scheduler({"hierarchy": 1000})
        clock.advance(1.1)
        started = sched.begin("hierarchy", clock())
        self.assertTrue(started)
        self.assertTrue(sched.in_flight("hierarchy"))

    def test_begin_while_in_flight_coalesces(self) -> None:
        sched, clock = make_scheduler({"hierarchy": 1000})
        clock.advance(1.1)
        sched.begin("hierarchy", clock())
        started2 = sched.begin("hierarchy", clock())
        self.assertFalse(started2)

    def test_finish_clears_in_flight(self) -> None:
        sched, clock = make_scheduler({"hierarchy": 1000})
        clock.advance(1.1)
        sched.begin("hierarchy", clock())
        sched.finish("hierarchy")
        self.assertFalse(sched.in_flight("hierarchy"))


class TestComponentRefreshSchedulerPause(unittest.TestCase):
    def test_paused_component_not_due(self) -> None:
        sched, clock = make_scheduler({"assets": 500})
        clock.advance(1.0)
        sched.pause("assets")
        self.assertNotIn("assets", sched.collect_due())

    def test_resumed_component_becomes_due(self) -> None:
        sched, clock = make_scheduler({"assets": 500})
        clock.advance(1.0)
        sched.pause("assets")
        sched.resume("assets")
        self.assertIn("assets", sched.collect_due())

    def test_is_paused(self) -> None:
        sched, _ = make_scheduler({"x": 1000})
        sched.pause("x")
        self.assertTrue(sched.is_paused("x"))
        sched.resume("x")
        self.assertFalse(sched.is_paused("x"))


class TestComponentRefreshSchedulerRequestRefresh(unittest.TestCase):
    def test_request_refresh_makes_component_due_immediately(self) -> None:
        sched, _clock = make_scheduler({"console": 5000})
        sched.request_refresh("console")
        self.assertIn("console", sched.collect_due())

    def test_request_refresh_cleared_on_begin(self) -> None:
        sched, clock = make_scheduler({"console": 5000})
        sched.request_refresh("console")
        sched.begin("console", clock())
        sched.finish("console")
        # Should be cleared
        self.assertFalse(sched._records["console"].refresh_requested)


class TestComponentRefreshSchedulerSetInterval(unittest.TestCase):
    def test_set_interval_updates_schedule(self) -> None:
        sched, clock = make_scheduler({"preview": 10000})
        clock.advance(0.1)
        sched.set_interval("preview", 100, clock())
        clock.advance(0.2)
        self.assertIn("preview", sched.collect_due())

    def test_set_interval_negative_raises(self) -> None:
        sched, _clock = make_scheduler({"x": 1000})
        with self.assertRaises(ValueError):
            sched.set_interval("x", -1, 0.0)

    def test_set_interval_zero_raises(self) -> None:
        sched, _clock = make_scheduler({"x": 1000})
        with self.assertRaises(ValueError):
            sched.set_interval("x", 0, 0.0)


class TestComponentRefreshSchedulerHasPendingWork(unittest.TestCase):
    def test_no_pending_initially(self) -> None:
        sched, _ = make_scheduler({"x": 1000})
        self.assertFalse(sched.has_pending_work())

    def test_has_pending_when_in_flight(self) -> None:
        sched, clock = make_scheduler({"x": 1000})
        clock.advance(1.1)
        sched.begin("x", clock())
        self.assertTrue(sched.has_pending_work())


class TestComponentRefreshSchedulerNextDeadline(unittest.TestCase):
    def test_next_deadline_returns_future_time(self) -> None:
        # Initial next_due is 0.0 so deadline is 0.0 at start.
        # After begin+finish at t=0, next_due advances to interval seconds.
        sched, _clock = make_scheduler({"x": 2000})
        sched.begin("x", 0.0)
        sched.finish("x")
        deadline = sched.next_deadline(now=0.0)
        self.assertIsNotNone(deadline)
        assert deadline is not None
        self.assertGreater(deadline, 0.0)  # next_due is now 2.0


if __name__ == "__main__":
    unittest.main()
