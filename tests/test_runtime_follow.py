"""Tests for the renderer-neutral exponential follow contract."""

import unittest
from math import inf

from expra_engine.runtime.follow import exponential_follow


class TestExponentialFollow(unittest.TestCase):
    def test_position_converges_exponentially_toward_target(self) -> None:
        current = (0.0, 0.0)
        target = (10.0, -4.0)

        updated = exponential_follow(current, target, delta=0.5, speed=2.0)

        self.assertAlmostEqual(updated[0], 10.0 * (1.0 - 2.718281828459045**-1.0))
        self.assertAlmostEqual(updated[1], -4.0 * (1.0 - 2.718281828459045**-1.0))

    def test_zero_speed_and_zero_delta_preserve_position(self) -> None:
        self.assertEqual(exponential_follow((2.0, 3.0), (9.0, 9.0), 1.0, 0.0), (2.0, 3.0))
        self.assertEqual(exponential_follow((2.0, 3.0), (9.0, 9.0), 0.0, 4.0), (2.0, 3.0))

    def test_negative_speed_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            exponential_follow((0.0, 0.0), (1.0, 1.0), 0.1, -1.0)

    def test_large_delta_reaches_target_without_overshoot(self) -> None:
        updated = exponential_follow((0.0, 0.0), (10.0, -4.0), 1_000.0, 2.0)

        self.assertEqual(updated, (10.0, -4.0))

    def test_rejects_non_finite_delta(self) -> None:
        with self.assertRaises(ValueError):
            exponential_follow((0.0, 0.0), (1.0, 1.0), inf, 1.0)

    def test_accepts_plain_sequences_not_renderer_vectors(self) -> None:
        updated = exponential_follow([0, 0], [2, 4], 1.0, 1.0, offset=[1, -1])

        self.assertIsInstance(updated, tuple)
        self.assertGreater(updated[0], 0.0)
        self.assertGreater(updated[1], 0.0)


if __name__ == "__main__":
    unittest.main()
