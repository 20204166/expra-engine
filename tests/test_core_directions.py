"""Tests for named unit-vector direction constants."""

from __future__ import annotations

import math
import unittest

from expra_engine.core.directions import ALL, DOWN, LEFT, RIGHT, UP, UP_LEFT


class DirectionTests(unittest.TestCase):
    def test_up_is_unit_vector(self) -> None:
        self.assertAlmostEqual(math.hypot(*UP), 1.0)

    def test_all_are_unit_vectors(self) -> None:
        for direction in ALL:
            with self.subTest(direction=direction):
                self.assertAlmostEqual(math.hypot(*direction), 1.0, places=6)

    def test_up_is_positive_y(self) -> None:
        self.assertEqual(UP, (0.0, 1.0))

    def test_down_is_negative_y(self) -> None:
        self.assertEqual(DOWN, (0.0, -1.0))

    def test_cardinal_directions_are_axis_aligned(self) -> None:
        self.assertEqual(LEFT, (-1.0, 0.0))
        self.assertEqual(RIGHT, (1.0, 0.0))

    def test_diagonal_direction_has_equal_components(self) -> None:
        self.assertAlmostEqual(abs(UP_LEFT[0]), abs(UP_LEFT[1]))


if __name__ == "__main__":
    unittest.main()
