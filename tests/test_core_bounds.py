from __future__ import annotations

import math
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

    def test_rejects_non_finite_coordinates(self) -> None:
        finite = (0.0, 0.0, 1.0, 1.0)
        for index in range(4):
            for bad in (float("nan"), float("inf"), float("-inf")):
                values = list(finite)
                values[index] = bad
                with self.assertRaises(ValueError, msg=f"{values}"):
                    Bounds2D(*values)

    def test_rejects_non_finite_via_from_center_size(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError, msg=f"width={bad}"):
                Bounds2D.from_center_size(0.0, 0.0, bad, 1.0)
            with self.assertRaises(ValueError, msg=f"height={bad}"):
                Bounds2D.from_center_size(0.0, 0.0, 1.0, bad)

    def test_rejects_non_finite_via_expand(self) -> None:
        bounds = Bounds2D(0.0, 0.0, 1.0, 1.0)
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError, msg=f"amount={bad}"):
                bounds.expand(bad)

    def test_finite_coordinates_produce_finite_geometry(self) -> None:
        bounds = Bounds2D.from_center_size(5.0, 5.0, 4.0, 2.0)
        self.assertTrue(all(math.isfinite(v) for v in (bounds.width, bounds.height)))
        self.assertTrue(all(math.isfinite(v) for v in (bounds.center_x, bounds.center_y)))


if __name__ == "__main__":
    unittest.main()
