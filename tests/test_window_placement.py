from __future__ import annotations

import unittest

from expra_engine.editor.window_placement import WindowGeometry


class WindowGeometryTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        geometry = WindowGeometry(1280, 800, 100, 50)
        self.assertEqual(WindowGeometry.from_tk_geometry(geometry.to_tk_geometry()), geometry)

    def test_invalid_string_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("invalid"))
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x600"))

    def test_negative_position_is_supported(self) -> None:
        geometry = WindowGeometry.from_tk_geometry("800x600+-10+-20")
        self.assertIsNotNone(geometry)
        assert geometry is not None
        self.assertEqual((geometry.x, geometry.y), (-10, -20))

    def test_invalid_dimensions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(0, 800, 0, 0)
        self.assertIsNone(WindowGeometry.from_tk_geometry("0x600+0+0"))


if __name__ == "__main__":
    unittest.main()
