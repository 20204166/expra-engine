"""Tests for TimerDelivery — Tk timer lifecycle and safe delivery.

Adapted from System Analyzer tests/test_window_supports.py TimerDeliveryTests
— imports updated to expra_engine; all test logic preserved.
"""

import unittest
from collections.abc import Callable
from typing import cast
from unittest.mock import Mock

from expra_engine.ui.timer_delivery import TimerDelivery, deadline_delay_ms
from tests.support.scheduling import FailingCancelMaster, TimerMaster


class TimerDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.master = TimerMaster()
        self.pending_ids: set[str] = set()
        self.delivery = TimerDelivery(
            master=self.master,
            is_closing=lambda: False,
            pending_ids=self.pending_ids,
            logger=Mock(),
        )

    def test_schedule_tracks_and_removes_timer_before_delivery(self) -> None:
        callback = Mock()
        identifier = self.delivery.schedule(500, callback, "payload")

        self.assertEqual(identifier, "after#1")
        self.assertIn("after#1", self.pending_ids)
        cast(Callable[[], None], self.master.scheduled[0][1])()

        self.assertNotIn("after#1", self.pending_ids)
        callback.assert_called_once_with("payload")

    def test_cancel_removes_timer(self) -> None:
        identifier = self.delivery.schedule(500, Mock())
        assert identifier is not None

        self.assertTrue(self.delivery.cancel(identifier))
        self.assertNotIn(identifier, self.pending_ids)
        self.assertEqual(self.master.cancelled, [identifier])

    def test_schedule_suppresses_work_when_closing(self) -> None:
        delivery = TimerDelivery(
            master=self.master,
            is_closing=lambda: True,
            pending_ids=self.pending_ids,
            logger=Mock(),
        )

        self.assertIsNone(delivery.schedule(500, Mock()))
        self.assertEqual(self.master.scheduled, [])

    def test_cancel_failure_clears_identifier_while_closing(self) -> None:
        master = FailingCancelMaster()
        pending_ids = {"after#1"}
        delivery = TimerDelivery(
            master=master,
            is_closing=lambda: True,
            pending_ids=pending_ids,
            logger=Mock(),
        )

        self.assertFalse(delivery.cancel("after#1"))
        self.assertEqual(pending_ids, set())

    def test_invoke_logs_and_swallows_callback_failure(self) -> None:
        logger = Mock()

        TimerDelivery.invoke(Mock(side_effect=RuntimeError("dead widget")), logger)

        logger.warning.assert_called_once()

    def test_timer_interrupt_closes_window_instead_of_reentering_tk(self) -> None:
        close = Mock()
        delivery = TimerDelivery(
            master=self.master,
            is_closing=lambda: False,
            pending_ids=self.pending_ids,
            logger=Mock(),
            on_interrupt=close,
        )
        identifier = delivery.schedule(500, Mock(side_effect=KeyboardInterrupt()))
        assert identifier is not None

        cast(Callable[[], None], self.master.scheduled[0][1])()

        close.assert_called_once_with()
        self.assertNotIn(identifier, self.pending_ids)

    def test_deadline_delay_is_milliseconds_and_never_negative(self) -> None:
        self.assertEqual(deadline_delay_ms(12.25, 12.0), 250)
        self.assertEqual(deadline_delay_ms(11.9, 12.0), 0)


if __name__ == "__main__":
    unittest.main()
