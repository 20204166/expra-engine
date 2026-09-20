from __future__ import annotations

import math
import unittest

from expra_engine.core.math_utils import (
    clamp,
    inverselerp,
    lerp,
    lerp_angle,
    lerp_exponential_decay,
    round_to_closest,
)


class MathUtilsTests(unittest.TestCase):
    def test_clamp_bounds_and_invalid_range(self) -> None:
        self.assertEqual(clamp(5.0, 0.0, 10.0), 5.0)
        self.assertEqual(clamp(-1.0, 0.0, 10.0), 0.0)
        self.assertEqual(clamp(11.0, 0.0, 10.0), 10.0)
        self.assertEqual(clamp(3.0, 5.0, 5.0), 5.0)
        with self.assertRaises(ValueError):
            clamp(5.0, 10.0, 0.0)

    def test_lerp_allows_extrapolation(self) -> None:
        self.assertEqual(lerp(0.0, 10.0, 0.0), 0.0)
        self.assertEqual(lerp(0.0, 10.0, 1.0), 10.0)
        self.assertEqual(lerp(0.0, 10.0, 2.0), 20.0)

    def test_inverselerp_and_degenerate_range(self) -> None:
        self.assertEqual(inverselerp(0.0, 10.0, 5.0), 0.5)
        with self.assertRaises(ValueError):
            inverselerp(1.0, 1.0, 1.0)

    def test_lerp_angle_uses_shortest_arc(self) -> None:
        self.assertAlmostEqual(lerp_angle(0.0, 90.0, 0.5), 45.0)
        self.assertAlmostEqual(lerp_angle(350.0, 10.0, 0.5), 360.0)

    def test_exponential_decay_is_frame_rate_independent(self) -> None:
        one_step = lerp_exponential_decay(0.0, 10.0, 1.0, 5.0)
        two_steps = lerp_exponential_decay(
            lerp_exponential_decay(0.0, 10.0, 0.5, 5.0), 10.0, 0.5, 5.0
        )
        self.assertAlmostEqual(one_step, two_steps)
        self.assertEqual(lerp_exponential_decay(0.0, 10.0, 0.0, 5.0), 0.0)

    def test_round_to_closest(self) -> None:
        self.assertAlmostEqual(round_to_closest(0.26, 0.1), 0.3)
        with self.assertRaises(ValueError):
            round_to_closest(1.0, 0.0)


class MathUtilsFiniteTests(unittest.TestCase):
    def test_decay_handles_large_positive_dt(self) -> None:
        self.assertAlmostEqual(lerp_exponential_decay(0.0, 10.0, 100.0, 5.0), 10.0)

    def test_halfway_decay(self) -> None:
        self.assertAlmostEqual(lerp_exponential_decay(0.0, 10.0, 1.0, math.log(2.0)), 5.0)


if __name__ == "__main__":
    unittest.main()
