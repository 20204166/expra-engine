from __future__ import annotations

import math
import unittest

from expra_engine.ui_model.slider import SliderModel


class SliderModelTests(unittest.TestCase):
    def test_default_value_and_fraction(self) -> None:
        slider = SliderModel(0.0, 10.0)
        self.assertEqual(slider.value, 0.0)
        self.assertEqual(slider.fraction, 0.0)

    def test_value_is_clamped(self) -> None:
        slider = SliderModel(0.0, 10.0)
        slider.value = 15.0
        self.assertEqual(slider.value, 10.0)
        slider.value = -5.0
        self.assertEqual(slider.value, 0.0)

    def test_value_snaps_to_step(self) -> None:
        slider = SliderModel(0.0, 1.0, step=0.1)
        slider.value = 0.26
        self.assertAlmostEqual(slider.value, 0.3)
        slider.value = 0.35
        self.assertAlmostEqual(slider.value, 0.3)

    def test_invalid_configuration_raises(self) -> None:
        with self.assertRaises(ValueError):
            SliderModel(1.0, 0.0)
        with self.assertRaises(ValueError):
            SliderModel(0.0, 1.0, step=-0.1)

    def test_fraction_tracks_value(self) -> None:
        slider = SliderModel(-10.0, 10.0)
        slider.value = 0.0
        self.assertEqual(slider.fraction, 0.5)

    def test_equal_bounds_raise(self) -> None:
        with self.assertRaises(ValueError):
            SliderModel(1.0, 1.0)

    def test_nan_and_infinite_bounds_raise(self) -> None:
        with self.assertRaises(ValueError):
            SliderModel(math.nan, 1.0)
        with self.assertRaises(ValueError):
            SliderModel(0.0, math.inf)

    def test_nan_and_infinite_step_raise(self) -> None:
        with self.assertRaises(ValueError):
            SliderModel(0.0, 1.0, step=math.nan)
        with self.assertRaises(ValueError):
            SliderModel(0.0, 1.0, step=math.inf)

    def test_nan_and_infinite_value_assignment_raise(self) -> None:
        slider = SliderModel(0.0, 10.0)
        with self.assertRaises(ValueError):
            slider.value = math.nan
        with self.assertRaises(ValueError):
            slider.value = math.inf

    def test_step_larger_than_range_snaps_to_a_bound(self) -> None:
        slider = SliderModel(0.0, 10.0, step=100.0)
        slider.value = 6.0
        self.assertEqual(slider.value, 0.0)

    def test_fraction_at_max_bound(self) -> None:
        slider = SliderModel(0.0, 10.0)
        slider.value = 10.0
        self.assertEqual(slider.fraction, 1.0)


if __name__ == "__main__":
    unittest.main()
