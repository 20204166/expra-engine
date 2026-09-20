"""Edge/regression tests for RuntimeClock pause/unscaled-time semantics."""

import unittest

from expra_engine.runtime.clock import RuntimeClock
from expra_engine.runtime.events import Idle, Update


def _collect(clock: RuntimeClock, delta: float) -> list[Update]:
    events: list[Update] = []
    clock.on_idle(Idle(delta), events.append)
    return events


class PauseTests(unittest.TestCase):
    def test_paused_clock_emits_no_updates(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0)
        clock.pause()
        updates = _collect(clock, 1.0)
        self.assertEqual(updates, [])

    def test_resume_after_pause_emits_updates_again(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0)
        clock.pause()
        _collect(clock, 1.0)
        clock.resume()
        updates = _collect(clock, 1.0 / 60.0)
        self.assertEqual(len(updates), 1)

    def test_resume_has_no_spike(self) -> None:
        """After pause + resume the first tick must not produce many updates."""
        clock = RuntimeClock(time_step=1.0 / 60.0)
        clock.pause()
        # Simulate 2 seconds of wall time passing while paused
        for _ in range(120):
            _collect(clock, 1.0 / 60.0)
        clock.resume()
        updates = _collect(clock, 1.0 / 60.0)
        self.assertLessEqual(len(updates), 1)

    def test_paused_flag(self) -> None:
        clock = RuntimeClock()
        self.assertFalse(clock.paused)
        clock.pause()
        self.assertTrue(clock.paused)
        clock.resume()
        self.assertFalse(clock.paused)

    def test_unscaled_elapsed_advances_while_paused(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0)
        clock.pause()
        _collect(clock, 0.5)
        _collect(clock, 0.5)
        self.assertAlmostEqual(clock.unscaled_elapsed, 1.0, places=6)

    def test_unscaled_elapsed_advances_when_not_paused(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0)
        _collect(clock, 0.1)
        _collect(clock, 0.2)
        self.assertAlmostEqual(clock.unscaled_elapsed, 0.3, places=6)


class TimeScaleTests(unittest.TestCase):
    def test_time_scale_zero_suppresses_updates(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0, time_scale=0.0)
        updates = _collect(clock, 1.0)
        self.assertEqual(updates, [])

    def test_time_scale_zero_unscaled_still_advances(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0, time_scale=0.0)
        _collect(clock, 0.5)
        self.assertAlmostEqual(clock.unscaled_elapsed, 0.5)

    def test_negative_time_scale_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeClock(time_scale=-0.1)

    def test_reset_clears_accumulated_and_unscaled(self) -> None:
        clock = RuntimeClock(time_step=1.0 / 60.0)
        _collect(clock, 0.5)
        clock.reset()
        self.assertEqual(clock.unscaled_elapsed, 0.0)
        self.assertFalse(clock.paused)


if __name__ == "__main__":
    unittest.main()
