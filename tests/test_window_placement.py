from __future__ import annotations

import importlib.util
import unittest

from expra_engine.editor import window_placement
from expra_engine.editor.window_placement import WindowGeometry


class InitialHierarchyWidthTests(unittest.TestCase):
    def test_initial_hierarchy_width_is_responsive_and_clamped(self) -> None:
        choose_width = getattr(window_placement, "initial_hierarchy_width", None)
        self.assertTrue(callable(choose_width), "window placement must own the pane width policy")
        assert callable(choose_width)
        self.assertEqual(choose_width(1648), 494)
        self.assertEqual(choose_width(1280), 384)
        self.assertEqual(choose_width(900), 360)
        self.assertEqual(choose_width(3000), 500)
        self.assertEqual(choose_width(700), 190)

    def test_window_placement_owns_responsive_sidebar_policy(self) -> None:
        spec = importlib.util.find_spec("expra_engine.editor.window_placement")
        self.assertIsNotNone(spec)
        self.assertTrue(callable(getattr(window_placement, "initial_hierarchy_width", None)))


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


class TestFromTkGeometryMalformed(unittest.TestCase):
    """from_tk_geometry must return None for every non-canonical string.

    The editor supplies ``preferences.window_geometry or ""`` at startup; any
    bad stored value must silently produce None so the window falls back to its
    default geometry instead of raising.
    """

    def test_empty_string_returns_none(self) -> None:
        # canonical editor fallback: ``self._preferences.window_geometry or ""``
        self.assertIsNone(WindowGeometry.from_tk_geometry(""))

    def test_one_offset_only_returns_none(self) -> None:
        # missing second offset — not a complete geometry string
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x600+100"))

    def test_whitespace_prefix_returns_none(self) -> None:
        # a hand-edited preferences file may have leading whitespace
        self.assertIsNone(WindowGeometry.from_tk_geometry(" 800x600+0+0"))

    def test_whitespace_suffix_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x600+0+0 "))

    def test_fractional_dimension_returns_none(self) -> None:
        # "800.5" is not matched by \d+
        self.assertIsNone(WindowGeometry.from_tk_geometry("800.5x600+0+0"))

    def test_negative_width_via_hyphen_returns_none(self) -> None:
        # negative dimensions cannot enter the model via parsing:
        # the \d+ group does not match a leading '-'
        self.assertIsNone(WindowGeometry.from_tk_geometry("-800x600+0+0"))

    def test_negative_height_via_hyphen_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x-600+0+0"))

    def test_bare_dimensions_without_origin_return_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x600"))

    def test_garbage_string_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("not a geometry"))

    def test_zero_width_returns_none(self) -> None:
        # cls(0, 600, 0, 0) raises ValueError in __post_init__; from_tk_geometry returns None
        self.assertIsNone(WindowGeometry.from_tk_geometry("0x600+0+0"))

    def test_zero_height_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("800x0+0+0"))

    def test_both_dimensions_zero_returns_none(self) -> None:
        self.assertIsNone(WindowGeometry.from_tk_geometry("0x0+0+0"))


class TestFromTkGeometryValid(unittest.TestCase):
    """from_tk_geometry must parse every valid Tk geometry string correctly."""

    def test_zero_origin_coordinates(self) -> None:
        geometry = WindowGeometry.from_tk_geometry("800x600+0+0")
        self.assertEqual(geometry, WindowGeometry(800, 600, 0, 0))

    def test_minimum_valid_size(self) -> None:
        # 1x1 is the smallest valid geometry the model accepts
        geometry = WindowGeometry.from_tk_geometry("1x1+0+0")
        self.assertEqual(geometry, WindowGeometry(1, 1, 0, 0))

    def test_negative_offsets_parse_to_correct_fields(self) -> None:
        geometry = WindowGeometry.from_tk_geometry("800x600+-10+-20")
        self.assertEqual(geometry, WindowGeometry(800, 600, -10, -20))

    def test_far_off_screen_negative_coordinates_are_preserved(self) -> None:
        # Windows on a second monitor can have large negative coordinates;
        # the model preserves them faithfully without clamping.
        geometry = WindowGeometry.from_tk_geometry("1280x800+-32768+-32768")
        self.assertEqual(geometry, WindowGeometry(1280, 800, -32768, -32768))

    def test_large_positive_coordinates(self) -> None:
        geometry = WindowGeometry.from_tk_geometry("2560x1440+3840+0")
        self.assertEqual(geometry, WindowGeometry(2560, 1440, 3840, 0))

    def test_positive_y_only(self) -> None:
        geometry = WindowGeometry.from_tk_geometry("800x600+0+100")
        self.assertEqual(geometry, WindowGeometry(800, 600, 0, 100))


class TestRoundTrip(unittest.TestCase):
    """to_tk_geometry → from_tk_geometry must be an identity for every valid WindowGeometry."""

    def test_zero_origin_round_trips(self) -> None:
        geometry = WindowGeometry(800, 600, 0, 0)
        self.assertEqual(WindowGeometry.from_tk_geometry(geometry.to_tk_geometry()), geometry)

    def test_negative_offset_round_trips_with_full_equality(self) -> None:
        # The original test only checked x,y; this asserts the whole geometry.
        geometry = WindowGeometry(800, 600, -10, -20)
        self.assertEqual(WindowGeometry.from_tk_geometry(geometry.to_tk_geometry()), geometry)

    def test_positive_offset_round_trips(self) -> None:
        geometry = WindowGeometry(1920, 1080, 100, 200)
        self.assertEqual(WindowGeometry.from_tk_geometry(geometry.to_tk_geometry()), geometry)

    def test_far_negative_offset_round_trips(self) -> None:
        geometry = WindowGeometry(1280, 800, -32768, -32768)
        self.assertEqual(WindowGeometry.from_tk_geometry(geometry.to_tk_geometry()), geometry)


class TestPostInit(unittest.TestCase):
    """__post_init__ must reject every WindowGeometry with non-positive dimensions."""

    def test_zero_width_raises(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(0, 800, 0, 0)

    def test_zero_height_raises(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(800, 0, 0, 0)

    def test_negative_width_raises(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(-1, 800, 0, 0)

    def test_negative_height_raises(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(800, -1, 0, 0)

    def test_both_dimensions_negative_raises(self) -> None:
        with self.assertRaises(ValueError):
            WindowGeometry(-1, -1, 0, 0)

    def test_valid_minimum_does_not_raise(self) -> None:
        # Must not raise; negative coordinates are valid (off-screen placement)
        geom = WindowGeometry(1, 1, -9999, -9999)
        self.assertEqual(geom.width, 1)
        self.assertEqual(geom.height, 1)


if __name__ == "__main__":
    unittest.main()
