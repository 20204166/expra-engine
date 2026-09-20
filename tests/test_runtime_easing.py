from __future__ import annotations

import math
import unittest

from expra_engine.runtime.easing import (
    CubicBezier,
    combine,
    in_back,
    in_bounce,
    in_circ,
    in_cubic,
    in_elastic,
    in_expo,
    in_out_back,
    in_out_bounce,
    in_out_circ,
    in_out_cubic,
    in_out_elastic,
    in_out_expo,
    in_out_quad,
    in_out_quart,
    in_out_quint,
    in_out_sine,
    in_quad,
    in_quart,
    in_quint,
    in_sine,
    linear,
    out_back,
    out_bounce,
    out_circ,
    out_cubic,
    out_elastic,
    out_expo,
    out_quad,
    out_quart,
    out_quint,
    out_sine,
    reverse,
)

EASINGS = [
    linear,
    in_sine,
    out_sine,
    in_out_sine,
    in_quad,
    out_quad,
    in_out_quad,
    in_cubic,
    out_cubic,
    in_out_cubic,
    in_quart,
    out_quart,
    in_out_quart,
    in_quint,
    out_quint,
    in_out_quint,
    in_expo,
    out_expo,
    in_out_expo,
    in_circ,
    out_circ,
    in_out_circ,
    in_back,
    out_back,
    in_out_back,
    in_elastic,
    out_elastic,
    in_out_elastic,
    in_bounce,
    out_bounce,
    in_out_bounce,
]


class EasingTests(unittest.TestCase):
    def test_all_easings_have_endpoint_values(self) -> None:
        for easing in EASINGS:
            with self.subTest(easing=easing.__name__):
                self.assertAlmostEqual(easing(0.0), 0.0, places=6)
                self.assertAlmostEqual(easing(1.0), 1.0, places=6)

    def test_nonfinite_progress_is_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                in_quad(value)

    def test_known_quadratic_and_sine_values(self) -> None:
        self.assertEqual(in_quad(0.5), 0.25)
        self.assertAlmostEqual(out_sine(0.5), math.sqrt(0.5))
        self.assertAlmostEqual(in_out_quad(0.25), 0.125)

    def test_reverse_and_combine(self) -> None:
        self.assertEqual(reverse(linear)(0.0), 1.0)
        self.assertEqual(reverse(linear)(1.0), 0.0)
        self.assertEqual(combine(in_quad, out_quad)(0.0), 0.0)
        self.assertEqual(combine(in_quad, out_quad)(1.0), 1.0)

    def test_combine_rejects_invalid_split(self) -> None:
        with self.assertRaises(ValueError):
            combine(linear, linear, 0.0)
        with self.assertRaises(ValueError):
            combine(linear, linear, 1.0)

    def test_cubic_bezier_endpoints_and_midpoint(self) -> None:
        curve = CubicBezier(0.25, 0.1, 0.25, 1.0)
        self.assertAlmostEqual(curve(0.0), 0.0)
        self.assertAlmostEqual(curve(1.0), 1.0)
        self.assertGreater(curve(0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
