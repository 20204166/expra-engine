"""Tests for RuntimeClock — fixed-timestep accumulator.

Edge cases adapted from ppb/systems/clocks.py Updater semantics
(PursuedPyBear, Artistic License 2.0). Translated to Expra API.

Tests cover:
  - fixed step fires at correct accumulated time
  - partial accumulation does not fire early
  - multiple Updates per Idle when dt > time_step (catch-up)
  - leftover fraction carries to next Idle (no loss)
  - pause/reset discards accumulated time
  - invalid time_step raises ValueError
  - zero dt is safe
"""

import unittest
from math import inf, nan
from typing import Any

from expra_engine.runtime.clock import RuntimeClock
from expra_engine.runtime.events import Idle, Update


class _Collector:
    """Signal sink that records dispatched events."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def __call__(self, event: Any) -> None:
        self.events.append(event)


class TestRuntimeClockFixed(unittest.TestCase):
    STEP = 1.0 / 60.0

    def _make(self) -> RuntimeClock:
        return RuntimeClock(time_step=self.STEP)

    def _idle(self, clock: RuntimeClock, dt: float) -> _Collector:
        collector = _Collector()
        clock.on_idle(Idle(dt), collector)
        return collector

    def test_exact_one_step_fires_one_update(self) -> None:
        clock = self._make()
        c = self._idle(clock, self.STEP)
        updates = [e for e in c.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 1)
        self.assertAlmostEqual(updates[0].time_delta, self.STEP)

    def test_half_step_fires_no_update(self) -> None:
        clock = self._make()
        c = self._idle(clock, self.STEP / 2)
        updates = [e for e in c.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 0)

    def test_two_steps_fires_two_updates(self) -> None:
        clock = self._make()
        c = self._idle(clock, self.STEP * 2)
        updates = [e for e in c.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 2)

    def test_fractional_carries_over(self) -> None:
        clock = self._make()
        half = self.STEP * 0.6
        self._idle(clock, half)  # 0.6 step — no update
        c2 = self._idle(clock, half)  # 1.2 steps — 1 update
        updates = [e for e in c2.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 1)

    def test_interpolation_fraction_reports_remainder(self) -> None:
        clock = RuntimeClock(time_step=0.1)
        self._idle(clock, 0.05)
        self.assertAlmostEqual(clock.interpolation_fraction, 0.5)

    def test_interpolation_fraction_is_zero_after_reset_and_update_boundary(self) -> None:
        clock = RuntimeClock(time_step=0.1)
        self._idle(clock, 0.1)
        self.assertAlmostEqual(clock.interpolation_fraction, 0.0)
        self._idle(clock, 0.03)
        clock.reset()
        self.assertAlmostEqual(clock.interpolation_fraction, 0.0)

    def test_zero_dt_safe(self) -> None:
        clock = self._make()
        c = self._idle(clock, 0.0)
        self.assertEqual(c.events, [])

    def test_update_time_delta_equals_time_step(self) -> None:
        clock = RuntimeClock(time_step=0.05)
        c = self._idle(clock, 0.11)
        updates = [e for e in c.events if isinstance(e, Update)]
        for u in updates:
            self.assertAlmostEqual(u.time_delta, 0.05)

    def test_reset_discards_accumulated(self) -> None:
        clock = self._make()
        self._idle(clock, self.STEP * 0.8)  # 0.8 step accumulated
        clock.reset()
        c = self._idle(clock, self.STEP * 0.4)  # fresh 0.4 — should not fire
        updates = [e for e in c.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 0)

    def test_invalid_time_step_raises(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeClock(time_step=0.0)

    def test_negative_time_step_raises(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeClock(time_step=-1.0)

    def test_non_finite_clock_configuration_raises(self) -> None:
        for time_step, time_scale in ((inf, 1.0), (nan, 1.0), (0.1, inf), (0.1, nan)):
            with self.subTest(time_step=time_step, time_scale=time_scale), self.assertRaises(ValueError):
                RuntimeClock(time_step=time_step, time_scale=time_scale)

    def test_non_finite_idle_delta_raises(self) -> None:
        clock = self._make()
        for delta in (nan, -inf):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                clock.on_idle(Idle(delta), _Collector())


class TestRuntimeClockCustomStep(unittest.TestCase):
    def test_custom_step(self) -> None:
        clock = RuntimeClock(time_step=0.1)
        c = _Collector()
        clock.on_idle(Idle(0.25), c)
        updates = [e for e in c.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 2)

    def test_remaining_fraction_after_custom(self) -> None:
        clock = RuntimeClock(time_step=0.1)
        c1 = _Collector()
        clock.on_idle(Idle(0.25), c1)  # 2 updates, 0.05 left
        c2 = _Collector()
        clock.on_idle(Idle(0.06), c2)  # 0.11 total — 1 update
        updates = [e for e in c2.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 1)


if __name__ == "__main__":
    unittest.main()
