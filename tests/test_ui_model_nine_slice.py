"""Tests for backend-neutral nine-slice patch geometry."""

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.ui_model.geometry import Insets, Rect
from expra_engine.ui_model.nine_slice import NineSlice, NineSlicePatch


class TestNineSliceGeometry(unittest.TestCase):
    def test_wide_panel_keeps_fixed_corners_and_stretches_edges_and_center(self) -> None:
        patches = NineSlice(Insets(10.0, 8.0, 10.0, 8.0)).resolve(Rect(0.0, 0.0, 100.0, 50.0))

        self.assertEqual(patches[0], NineSlicePatch("bottom_left", Rect(0.0, 0.0, 10.0, 8.0)))
        self.assertEqual(patches[1], NineSlicePatch("bottom", Rect(10.0, 0.0, 80.0, 8.0)))
        self.assertEqual(patches[4], NineSlicePatch("center", Rect(10.0, 8.0, 80.0, 34.0)))
        self.assertEqual(patches[7], NineSlicePatch("top", Rect(10.0, 42.0, 80.0, 8.0)))
        self.assertEqual(patches[8], NineSlicePatch("top_right", Rect(90.0, 42.0, 10.0, 8.0)))

    def test_tall_panel_stretches_vertical_edges_and_preserves_corners(self) -> None:
        patches = NineSlice(Insets(6.0, 5.0, 6.0, 5.0)).resolve(Rect(2.0, 3.0, 30.0, 100.0))

        self.assertEqual(patches[0].rect, Rect(2.0, 3.0, 6.0, 5.0))
        self.assertEqual(patches[3].rect, Rect(2.0, 8.0, 6.0, 90.0))
        self.assertEqual(patches[4].rect, Rect(8.0, 8.0, 18.0, 90.0))
        self.assertEqual(patches[5].rect, Rect(26.0, 8.0, 6.0, 90.0))

    def test_square_and_aspect_ratio_changes_only_change_stretched_rectangles(self) -> None:
        model = NineSlice(Insets(4.0, 4.0, 4.0, 4.0))

        square = model.resolve(Rect(0.0, 0.0, 20.0, 20.0))
        wide = model.resolve(Rect(0.0, 0.0, 40.0, 20.0))

        self.assertEqual((square[0].rect.width, square[0].rect.height), (4.0, 4.0))
        self.assertEqual((wide[8].rect.width, wide[8].rect.height), (4.0, 4.0))
        self.assertEqual(square[4].rect, Rect(4.0, 4.0, 12.0, 12.0))
        self.assertEqual(wide[4].rect, Rect(4.0, 4.0, 32.0, 12.0))

    def test_tiny_panel_clamps_each_axis_without_negative_rectangles(self) -> None:
        patches = NineSlice(Insets(10.0, 8.0, 12.0, 9.0)).resolve(Rect(0.0, 0.0, 5.0, 4.0))

        self.assertEqual(patches[0].rect, Rect(0.0, 0.0, 2.5, 2.0))
        self.assertEqual(patches[2].rect, Rect(2.5, 0.0, 2.5, 2.0))
        self.assertEqual(patches[6].rect, Rect(0.0, 2.0, 2.5, 2.0))
        self.assertEqual(patches[8].rect, Rect(2.5, 2.0, 2.5, 2.0))
        for patch in patches:
            self.assertGreaterEqual(patch.rect.width, 0.0)
            self.assertGreaterEqual(patch.rect.height, 0.0)

    def test_zero_panel_returns_nine_empty_or_zero_area_patches(self) -> None:
        patches = NineSlice(Insets(2.0, 3.0, 4.0, 5.0)).resolve(Rect(7.0, 9.0, 0.0, 0.0))

        self.assertEqual(len(patches), 9)
        self.assertTrue(
            all(patch.rect.width == 0.0 or patch.rect.height == 0.0 for patch in patches)
        )

    def test_negative_dimensions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NineSlice(Insets(-1.0, 0.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            NineSlice(Insets()).resolve(Rect(0.0, 0.0, -1.0, 1.0))

    def test_outset_expands_the_outer_patch_bounds(self) -> None:
        patches = NineSlice(Insets(2.0, 3.0, 4.0, 5.0), outset=Insets(1.0, 2.0, 3.0, 4.0)).resolve(
            Rect(10.0, 20.0, 30.0, 40.0)
        )

        self.assertEqual(patches[0].rect, Rect(9.0, 16.0, 2.0, 5.0))
        self.assertEqual(patches[8].rect, Rect(39.0, 59.0, 4.0, 3.0))

    def test_padding_adds_fixed_space_to_each_edge_and_clamps(self) -> None:
        patches = NineSlice(Insets(2.0, 3.0, 2.0, 3.0), padding=Insets(1.0, 2.0, 1.0, 2.0)).resolve(
            Rect(0.0, 0.0, 20.0, 20.0)
        )

        self.assertEqual(patches[0].rect, Rect(0.0, 0.0, 3.0, 5.0))
        self.assertEqual(patches[4].rect, Rect(3.0, 5.0, 14.0, 10.0))

    def test_patch_records_and_result_are_immutable(self) -> None:
        patches = NineSlice(Insets()).resolve(Rect(0.0, 0.0, 1.0, 1.0))

        self.assertIsInstance(patches, tuple)
        with self.assertRaises(FrozenInstanceError):
            patches[0].name = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()


class NineSliceEdgeTests(unittest.TestCase):
    def test_extremely_wide_panel_no_negative_center(self) -> None:
        from expra_engine.ui_model.geometry import Insets, Rect
        from expra_engine.ui_model.nine_slice import NineSlice

        patches = NineSlice(Insets(10.0, 5.0, 10.0, 5.0)).resolve(Rect(0.0, 0.0, 10000.0, 20.0))
        center = next(p for p in patches if p.name == "center")
        self.assertGreaterEqual(center.rect.width, 0.0)
        self.assertGreaterEqual(center.rect.height, 0.0)

    def test_extremely_tall_panel_no_negative_center(self) -> None:
        from expra_engine.ui_model.geometry import Insets, Rect
        from expra_engine.ui_model.nine_slice import NineSlice

        patches = NineSlice(Insets(5.0, 10.0, 5.0, 10.0)).resolve(Rect(0.0, 0.0, 20.0, 10000.0))
        center = next(p for p in patches if p.name == "center")
        self.assertGreaterEqual(center.rect.height, 0.0)

    def test_fractional_dimensions(self) -> None:
        from expra_engine.ui_model.geometry import Insets, Rect
        from expra_engine.ui_model.nine_slice import NineSlice

        patches = NineSlice(Insets(2.5, 1.5, 2.5, 1.5)).resolve(Rect(0.0, 0.0, 7.5, 5.5))
        for p in patches:
            self.assertGreaterEqual(p.rect.width, 0.0)
            self.assertGreaterEqual(p.rect.height, 0.0)

    def test_corners_never_inverted_when_panel_smaller_than_combined_borders(self) -> None:
        from expra_engine.ui_model.geometry import Insets, Rect
        from expra_engine.ui_model.nine_slice import NineSlice

        patches = NineSlice(Insets(20.0, 20.0, 20.0, 20.0)).resolve(Rect(0.0, 0.0, 10.0, 10.0))
        for p in patches:
            self.assertGreaterEqual(p.rect.width, 0.0, f"Negative width in {p.name}")
            self.assertGreaterEqual(p.rect.height, 0.0, f"Negative height in {p.name}")
        corners = [
            p
            for p in patches
            if "_" in p.name and p.name not in ("bottom", "top", "left", "right", "center")
        ]
        self.assertEqual(len(corners), 4)

    def test_nine_patches_always_returned(self) -> None:
        from expra_engine.ui_model.geometry import Insets, Rect
        from expra_engine.ui_model.nine_slice import NineSlice

        for size in (0.0, 1.0, 100.0):
            patches = NineSlice(Insets(5.0, 5.0, 5.0, 5.0)).resolve(Rect(0.0, 0.0, size, size))
            self.assertEqual(len(patches), 9)
