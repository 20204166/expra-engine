"""Tests for the immutable Color type."""

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.core.color import Color


class ConstructionTests(unittest.TestCase):
    def test_default_is_opaque_black(self) -> None:
        c = Color()
        self.assertEqual(c.r, 0.0)
        self.assertEqual(c.g, 0.0)
        self.assertEqual(c.b, 0.0)
        self.assertEqual(c.a, 1.0)

    def test_channels_are_clamped(self) -> None:
        c = Color(r=2.0, g=-1.0, b=1.5, a=0.5)
        self.assertEqual(c.r, 1.0)
        self.assertEqual(c.g, 0.0)
        self.assertEqual(c.b, 1.0)
        self.assertEqual(c.a, 0.5)

    def test_non_finite_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Color(r=float("nan"))
        with self.assertRaises(ValueError):
            Color(a=float("inf"))

    def test_immutable(self) -> None:
        c = Color(0.5, 0.5, 0.5)
        with self.assertRaises(FrozenInstanceError):
            c.r = 1.0  # type: ignore[misc]


class HexParsingTests(unittest.TestCase):
    def test_rrggbb(self) -> None:
        c = Color.from_hex("#ff8800")
        self.assertAlmostEqual(c.r, 1.0)
        self.assertAlmostEqual(c.g, 136 / 255)
        self.assertAlmostEqual(c.b, 0.0)

    def test_rrggbbaa(self) -> None:
        c = Color.from_hex("ff880080")
        self.assertAlmostEqual(c.a, 128 / 255)

    def test_rgb_short(self) -> None:
        c = Color.from_hex("#f80")
        self.assertAlmostEqual(c.r, 1.0, places=4)
        self.assertAlmostEqual(c.g, 0x88 / 255, places=2)
        self.assertAlmostEqual(c.b, 0.0)

    def test_rgba_short(self) -> None:
        c = Color.from_hex("#f808")
        self.assertAlmostEqual(c.a, 0x88 / 255, places=2)

    def test_invalid_hex_raises(self) -> None:
        with self.assertRaises(ValueError):
            Color.from_hex("#zzzzzz")
        with self.assertRaises(ValueError):
            Color.from_hex("#ff")

    def test_without_hash(self) -> None:
        c = Color.from_hex("ffffff")
        self.assertEqual(c.r, 1.0)


class ConversionTests(unittest.TestCase):
    def test_rgba8_round_trip(self) -> None:
        c = Color.from_rgba8(100, 150, 200, 255)
        r8, g8, b8, a8 = c.rgba8
        self.assertAlmostEqual(r8, 100, delta=1)
        self.assertAlmostEqual(g8, 150, delta=1)
        self.assertAlmostEqual(b8, 200, delta=1)
        self.assertEqual(a8, 255)

    def test_hsv_round_trip(self) -> None:
        original = Color(0.6, 0.2, 0.8)
        h, s, v = original.hsv
        restored = Color.from_hsv(h, s, v, original.a)
        self.assertAlmostEqual(restored.r, original.r, places=5)
        self.assertAlmostEqual(restored.g, original.g, places=5)
        self.assertAlmostEqual(restored.b, original.b, places=5)

    def test_with_alpha_preserves_rgb(self) -> None:
        c = Color(0.5, 0.6, 0.7, 1.0)
        c2 = c.with_alpha(0.3)
        self.assertAlmostEqual(c2.a, 0.3)
        self.assertEqual(c2.r, c.r)


class BlendingTests(unittest.TestCase):
    def test_lerp_midpoint(self) -> None:
        black = Color(0.0, 0.0, 0.0)
        white = Color(1.0, 1.0, 1.0)
        mid = black.lerp(white, 0.5)
        self.assertAlmostEqual(mid.r, 0.5)

    def test_lerp_t0_returns_self(self) -> None:
        a = Color(0.2, 0.3, 0.4)
        result = a.lerp(Color(1.0, 1.0, 1.0), 0.0)
        self.assertAlmostEqual(result.r, a.r)

    def test_lerp_t1_returns_other(self) -> None:
        b = Color(0.9, 0.1, 0.5)
        result = Color(0.0, 0.0, 0.0).lerp(b, 1.0)
        self.assertAlmostEqual(result.r, b.r)

    def test_lerp_nan_raises(self) -> None:
        with self.assertRaises(ValueError):
            Color().lerp(Color(), float("nan"))

    def test_lerp_preserves_alpha(self) -> None:
        a = Color(0.0, 0.0, 0.0, 0.0)
        b = Color(1.0, 1.0, 1.0, 1.0)
        mid = a.lerp(b, 0.5)
        self.assertAlmostEqual(mid.a, 0.5)

    def test_tint_lightens(self) -> None:
        dark = Color(0.2, 0.2, 0.2)
        light = dark.tint(0.5)
        self.assertGreater(light.r, dark.r)

    def test_shade_darkens(self) -> None:
        bright = Color(0.8, 0.8, 0.8)
        dim = bright.shade(0.5)
        self.assertLess(dim.r, bright.r)

    def test_tint_preserves_alpha(self) -> None:
        c = Color(0.5, 0.5, 0.5, 0.7)
        self.assertAlmostEqual(c.tint(0.3).a, 0.7)

    def test_hsv_hue_wrap(self) -> None:
        c1 = Color.from_hsv(0.0, 1.0, 1.0)
        c2 = Color.from_hsv(1.0, 1.0, 1.0)
        self.assertAlmostEqual(c1.r, c2.r, places=5)


if __name__ == "__main__":
    unittest.main()
