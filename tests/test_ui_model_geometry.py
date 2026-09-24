"""Tests for backend-neutral UI layout geometry."""

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.ui_model.geometry import Insets, Rect, RectTransform


class TestRectTransformGeometry(unittest.TestCase):
    def test_center_anchor_and_pivot_resolve_fixed_size(self) -> None:
        transform = RectTransform(
            anchor_min=(0.5, 0.5),
            anchor_max=(0.5, 0.5),
            pivot=(0.5, 0.5),
            size=(100.0, 50.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 800.0, 600.0)), Rect(350.0, 275.0, 100.0, 50.0)
        )

    def test_fixed_size_uses_anchor_and_offset(self) -> None:
        transform = RectTransform(
            anchor_min=(0.0, 0.0),
            anchor_max=(0.0, 0.0),
            pivot=(0.0, 0.0),
            offset_min=(12.0, 18.0),
            size=(80.0, 40.0),
        )

        self.assertEqual(
            transform.resolve(Rect(10.0, 20.0, 400.0, 300.0)), Rect(22.0, 38.0, 80.0, 40.0)
        )

    def test_stretched_size_uses_both_anchors_and_offsets(self) -> None:
        transform = RectTransform(
            anchor_min=(0.0, 0.0),
            anchor_max=(1.0, 1.0),
            offset_min=(10.0, 20.0),
            offset_max=(30.0, 40.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 800.0, 600.0)), Rect(10.0, 20.0, 760.0, 540.0)
        )

    def test_minimum_and_maximum_size_clamp_stretched_result(self) -> None:
        transform = RectTransform(
            anchor_min=(0.0, 0.0),
            anchor_max=(0.0, 0.0),
            size=(10.0, 12.0),
            min_size=(40.0, 30.0),
            max_size=(60.0, 50.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 800.0, 600.0)), Rect(0.0, 0.0, 40.0, 30.0)
        )

    def test_maximum_size_clamps_fixed_result(self) -> None:
        transform = RectTransform(
            anchor_min=(0.0, 0.0),
            anchor_max=(0.0, 0.0),
            size=(100.0, 80.0),
            max_size=(60.0, 50.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 800.0, 600.0)), Rect(0.0, 0.0, 60.0, 50.0)
        )

    def test_maximum_size_clamp_repositions_fixed_centered_pivot(self) -> None:
        transform = RectTransform(
            anchor_min=(0.5, 0.5),
            anchor_max=(0.5, 0.5),
            pivot=(0.5, 0.5),
            size=(100.0, 80.0),
            max_size=(60.0, 50.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 800.0, 600.0)), Rect(370.0, 275.0, 60.0, 50.0)
        )

    def test_safe_area_insets_are_the_parent_for_anchored_layout(self) -> None:
        transform = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0))

        self.assertEqual(
            transform.resolve(
                Rect(0.0, 0.0, 800.0, 600.0), safe_area=Insets(20.0, 10.0, 30.0, 40.0)
            ),
            Rect(20.0, 10.0, 750.0, 550.0),
        )

    def test_reference_resolution_scales_fixed_size_per_axis(self) -> None:
        transform = RectTransform(
            anchor_min=(0.0, 0.0),
            anchor_max=(0.0, 0.0),
            size=(100.0, 50.0),
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 1600.0, 900.0), reference_resolution=(800.0, 600.0)),
            Rect(0.0, 0.0, 200.0, 75.0),
        )

    def test_dpi_scale_returns_logical_coordinates(self) -> None:
        transform = RectTransform(
            anchor_min=(0.5, 0.5), anchor_max=(0.5, 0.5), pivot=(0.5, 0.5), size=(100.0, 50.0)
        )

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 1600.0, 1200.0), dpi_scale=2.0),
            Rect(350.0, 275.0, 100.0, 50.0),
        )

    def test_arbitrary_aspect_ratio_keeps_normalized_anchor_position(self) -> None:
        transform = RectTransform(anchor_min=(0.25, 0.5), anchor_max=(0.25, 0.5), size=(20.0, 10.0))

        self.assertEqual(
            transform.resolve(Rect(0.0, 0.0, 1000.0, 500.0)), Rect(250.0, 250.0, 20.0, 10.0)
        )

    def test_negative_sizes_and_invalid_scale_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RectTransform(anchor_min=(0.0, 0.0), anchor_max=(0.0, 0.0), size=(-1.0, 10.0))
        with self.assertRaises(ValueError):
            RectTransform(anchor_min=(0.0, 0.0), anchor_max=(0.0, 0.0), min_size=(10.0, -1.0))
        with self.assertRaises(ValueError):
            RectTransform(anchor_min=(0.0, 0.0), anchor_max=(0.0, 0.0)).resolve(
                Rect(0.0, 0.0, 100.0, 100.0), dpi_scale=0.0
            )

    def test_inverted_safe_area_is_rejected(self) -> None:
        transform = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0))

        with self.assertRaises(ValueError):
            transform.resolve(Rect(0.0, 0.0, 100.0, 100.0), safe_area=Insets(60.0, 0.0, 50.0, 0.0))

    def test_model_is_immutable_and_uses_tuples(self) -> None:
        transform = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0))

        self.assertIsInstance(transform.anchor_min, tuple)
        with self.assertRaises(FrozenInstanceError):
            transform.pivot = (1.0, 1.0)  # type: ignore[misc]


class RectTransformEdgeTests(unittest.TestCase):
    def test_zero_size_parent_fixed_child(self) -> None:
        t = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(0.0, 0.0), size=(50.0, 30.0))
        result = t.resolve(Rect(0.0, 0.0, 0.0, 0.0))
        self.assertEqual(result.width, 50.0)
        self.assertEqual(result.height, 30.0)

    def test_tiny_parent_smaller_than_min_size(self) -> None:
        t = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0), min_size=(100.0, 80.0))
        result = t.resolve(Rect(0.0, 0.0, 10.0, 5.0))
        self.assertGreaterEqual(result.width, 100.0)
        self.assertGreaterEqual(result.height, 80.0)

    def test_non_centered_pivot_repositions_correctly(self) -> None:
        t = RectTransform(
            anchor_min=(0.0, 0.0), anchor_max=(0.0, 0.0), pivot=(0.0, 0.0), size=(60.0, 40.0)
        )
        result = t.resolve(Rect(0.0, 0.0, 200.0, 200.0))
        self.assertEqual(result.x, 0.0)
        self.assertEqual(result.y, 0.0)

    def test_negative_offset_moves_element(self) -> None:
        t = RectTransform(
            anchor_min=(0.5, 0.5),
            anchor_max=(0.5, 0.5),
            pivot=(0.5, 0.5),
            offset_min=(-20.0, -10.0),
            size=(40.0, 20.0),
        )
        result = t.resolve(Rect(0.0, 0.0, 200.0, 200.0))
        self.assertAlmostEqual(result.x, 60.0)
        self.assertAlmostEqual(result.y, 80.0)

    def test_stretched_anchors_fill_parent(self) -> None:
        t = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0))
        result = t.resolve(Rect(0.0, 0.0, 300.0, 200.0))
        self.assertAlmostEqual(result.width, 300.0)
        self.assertAlmostEqual(result.height, 200.0)

    def test_repeated_resize_produces_stable_result(self) -> None:
        t = RectTransform(anchor_min=(0.25, 0.25), anchor_max=(0.75, 0.75))
        sizes = [(400.0, 300.0), (800.0, 600.0), (400.0, 300.0)]
        results = [t.resolve(Rect(0.0, 0.0, w, h)) for w, h in sizes]
        self.assertEqual(results[0], results[2])

    def test_safe_area_larger_than_parent_raises(self) -> None:
        t = RectTransform(anchor_min=(0.0, 0.0), anchor_max=(1.0, 1.0))
        with self.assertRaises(ValueError):
            t.resolve(Rect(0.0, 0.0, 100.0, 100.0), safe_area=Insets(60.0, 0.0, 50.0, 0.0))


if __name__ == "__main__":
    unittest.main()
