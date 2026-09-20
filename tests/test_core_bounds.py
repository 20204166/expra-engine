from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.core.bounds import Bounds2D


class Bounds2DTests(unittest.TestCase):
    def test_dimensions_and_center(self) -> None:
        bounds = Bounds2D.from_center_size(5.0, 5.0, 4.0, 2.0)
        self.assertEqual((bounds.width, bounds.height), (4.0, 2.0))
        self.assertEqual((bounds.center_x, bounds.center_y), (5.0, 5.0))

    def test_invalid_order_raises(self) -> None:
        with self.assertRaises(ValueError):
            Bounds2D(5.0, 0.0, 0.0, 10.0)
        with self.assertRaises(ValueError):
            Bounds2D(0.0, 5.0, 10.0, 0.0)

    def test_contains_includes_edges(self) -> None:
        bounds = Bounds2D(0.0, 0.0, 10.0, 10.0)
        self.assertTrue(bounds.contains(0.0, 0.0))
        self.assertTrue(bounds.contains(10.0, 10.0))
        self.assertFalse(bounds.contains(10.1, 5.0))

    def test_intersects_excludes_only_touching_edges(self) -> None:
        self.assertTrue(Bounds2D(0, 0, 5, 5).intersects(Bounds2D(3, 3, 8, 8)))
        self.assertFalse(Bounds2D(0, 0, 5, 5).intersects(Bounds2D(5, 0, 10, 5)))

    def test_expand_returns_new_bounds(self) -> None:
        original = Bounds2D(2.0, 2.0, 8.0, 8.0)
        expanded = original.expand(1.0)
        self.assertEqual((expanded.min_x, expanded.max_x), (1.0, 9.0))
        self.assertEqual(original.min_x, 2.0)

    def test_is_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            Bounds2D(0, 0, 1, 1).min_x = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
