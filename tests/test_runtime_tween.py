from __future__ import annotations

import unittest

from expra_engine.runtime.easing import in_quad
from expra_engine.runtime.tween import Tween


class TweenTests(unittest.TestCase):
    def test_starts_at_start_and_ends_at_end(self) -> None:
        tween = Tween(0.0, 10.0, 2.0)
        self.assertEqual(tween.value, 0.0)
        tween.step(2.0)
        self.assertEqual(tween.value, 10.0)
        self.assertTrue(tween.finished)

    def test_midpoint_and_easing(self) -> None:
        self.assertEqual(Tween(0.0, 10.0, 2.0).step(1.0), 5.0)
        tween = Tween(0.0, 1.0, 1.0, easing=in_quad)
        self.assertAlmostEqual(tween.step(0.5), 0.25)

    def test_step_clamps_and_finished_tween_is_stable(self) -> None:
        tween = Tween(0.0, 5.0, 1.0)
        tween.step(100.0)
        self.assertEqual(tween.value, 5.0)
        self.assertEqual(tween.step(1.0), 5.0)

    def test_reset(self) -> None:
        tween = Tween(0.0, 10.0, 1.0)
        tween.step(1.0)
        tween.reset()
        self.assertFalse(tween.finished)
        self.assertEqual(tween.value, 0.0)

    def test_invalid_duration_and_dt_raise(self) -> None:
        with self.assertRaises(ValueError):
            Tween(0.0, 1.0, 0.0)
        with self.assertRaises(ValueError):
            Tween(0.0, 1.0, 1.0).step(-0.1)


if __name__ == "__main__":
    unittest.main()
