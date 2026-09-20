from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
