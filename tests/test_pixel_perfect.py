"""Tests for pixel-perfect integer-scaling math."""

import unittest

from expra_engine.core.pixel_perfect import PixelPerfectSettings


class ConstructionTests(unittest.TestCase):
    def test_zero_reference_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PixelPerfectSettings(0, 180)
        with self.assertRaises(ValueError):
            PixelPerfectSettings(320, 0)

    def test_invalid_ppu_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PixelPerfectSettings(320, 180, pixels_per_unit=0.0)
        with self.assertRaises(ValueError):
            PixelPerfectSettings(320, 180, pixels_per_unit=float("inf"))


class FitTests(unittest.TestCase):
    def test_320x180_to_1280x720_scale_4(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1280, 720)
        self.assertEqual(result.integer_scale, 4)
        self.assertEqual(result.scaled_width, 1280)
        self.assertEqual(result.scaled_height, 720)
        self.assertEqual(result.letterbox_x, 0)
        self.assertEqual(result.letterbox_y, 0)

    def test_320x180_to_1920x1080_scale_6(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1920, 1080)
        self.assertEqual(result.integer_scale, 6)
        self.assertEqual(result.scaled_width, 1920)
        self.assertEqual(result.scaled_height, 1080)

    def test_non_integer_multiple_chooses_floor(self) -> None:
        # 320 * 3 = 960, 180 * 3 = 540; 1000x600 allows scale 3
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1000, 600)
        self.assertEqual(result.integer_scale, 3)
        self.assertEqual(result.scaled_width, 960)
        self.assertEqual(result.scaled_height, 540)

    def test_aspect_mismatch_produces_letterbox(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1920, 1200)
        self.assertEqual(result.integer_scale, 6)
        self.assertEqual(result.scaled_width, 1920)
        self.assertEqual(result.scaled_height, 1080)
        self.assertGreater(result.letterbox_y, 0)

    def test_portrait_target(self) -> None:
        cfg = PixelPerfectSettings(180, 320)
        result = cfg.fit(360, 640)
        self.assertEqual(result.integer_scale, 2)
        self.assertEqual(result.scaled_width, 360)
        self.assertEqual(result.scaled_height, 640)

    def test_target_smaller_than_reference_uses_scale_1(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(160, 90)
        self.assertEqual(result.integer_scale, 1)
        self.assertGreaterEqual(result.scaled_width, 1)

    def test_scale_is_never_zero(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1, 1)
        self.assertGreaterEqual(result.integer_scale, 1)

    def test_letterbox_dimensions_sum_to_target(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        result = cfg.fit(1366, 768)
        self.assertEqual(result.letterbox_width, 1366)
        self.assertEqual(result.letterbox_height, 768)

    def test_zero_target_rejected(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        with self.assertRaises(ValueError):
            cfg.fit(0, 720)

    def test_repeated_fit_deterministic(self) -> None:
        cfg = PixelPerfectSettings(320, 180)
        r1 = cfg.fit(1280, 720)
        r2 = cfg.fit(1280, 720)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
