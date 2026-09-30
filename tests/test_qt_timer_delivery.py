"""QtTimerDelivery: tracked string-addressed timers for the shared window logic."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import Mock

from tests.support.qt_app import ensure_qt_app, pump_qt


class QtTimerDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        from expra_engine.editor.qt.timer_delivery import QtTimerDelivery

        ensure_qt_app()
        self.closing = False
        self.interrupted = Mock()
        self.delivery = QtTimerDelivery(
            is_closing=lambda: self.closing,
            logger=logging.getLogger("test"),
            on_interrupt=self.interrupted,
        )

    def test_schedule_tracks_and_removes_timer_before_delivery(self) -> None:
        callback = Mock()
        identifier = self.delivery.schedule(0, callback, "payload")

        self.assertIn(identifier, self.delivery.pending_ids)
        pump_qt(50)

        self.assertNotIn(identifier, self.delivery.pending_ids)
        callback.assert_called_once_with("payload")

    def test_cancel_removes_timer_and_it_never_fires(self) -> None:
        callback = Mock()
        identifier = self.delivery.schedule(0, callback)

        self.assertTrue(self.delivery.cancel(identifier))
        pump_qt(50)

        self.assertNotIn(identifier, self.delivery.pending_ids)
        callback.assert_not_called()

    def test_schedule_is_suppressed_while_closing(self) -> None:
        self.closing = True
        self.assertIsNone(self.delivery.schedule(0, Mock()))
        self.assertEqual(self.delivery.pending_ids, set())

    def test_a_timer_that_fires_while_closing_does_not_run(self) -> None:
        callback = Mock()
        self.delivery.schedule(0, callback)
        self.closing = True
        pump_qt(50)
        callback.assert_not_called()

    def test_cancel_all_drops_every_pending_timer(self) -> None:
        callbacks = [Mock(), Mock()]
        for callback in callbacks:
            self.delivery.schedule(0, callback)
        self.delivery.cancel_all()
        pump_qt(50)
        self.assertEqual(self.delivery.pending_ids, set())
        for callback in callbacks:
            callback.assert_not_called()

    def test_keyboard_interrupt_in_a_timer_closes_the_window_instead_of_propagating(self) -> None:
        identifier = self.delivery.schedule(0, Mock(side_effect=KeyboardInterrupt()))
        pump_qt(50)
        self.interrupted.assert_called_once_with()
        self.assertNotIn(identifier, self.delivery.pending_ids)


if __name__ == "__main__":
    unittest.main()
