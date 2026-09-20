"""Tests for the typed 2D grid (Grid2D[T])."""

import unittest

from expra_engine.core.grid2d import Grid2D


class ConstructionTests(unittest.TestCase):
    def test_basic_construction_with_default_factory(self) -> None:
        g: Grid2D[int] = Grid2D(3, 4, default_factory=int)
        self.assertEqual(g.width, 3)
        self.assertEqual(g.height, 4)
        for (_x, _y), v in g:
            self.assertEqual(v, 0)

    def test_zero_width_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(0, 4)

    def test_zero_height_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(3, 0)

    def test_negative_dimensions_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(-1, 4)
        with self.assertRaises(ValueError):
            Grid2D(3, -2)

    def test_ragged_data_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(2, 3, data=[[1, 2, 3], [4, 5]])

    def test_wrong_column_count_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(3, 2, data=[[1, 2], [3, 4]])

    def test_construction_from_data(self) -> None:
        data = [[10, 20], [30, 40]]
        g: Grid2D[int] = Grid2D(2, 2, data=data)
        self.assertEqual(g.get(0, 0), 10)
        self.assertEqual(g.get(1, 1), 40)

    def test_default_factory_called_once_per_cell_no_sharing(self) -> None:
        """Each mutable default must be independent (no shared object bug)."""
        g: Grid2D[list] = Grid2D(2, 2, default_factory=list)
        g.get(0, 0).append(99)  # type: ignore[union-attr]
        self.assertEqual(g.get(1, 1), [])  # other cell must be unaffected


class GetSetTests(unittest.TestCase):
    def test_get_in_bounds(self) -> None:
        g: Grid2D[str] = Grid2D(3, 3, default_factory=lambda: "x")
        g.set(1, 2, "y")
        self.assertEqual(g.get(1, 2), "y")

    def test_get_out_of_bounds_returns_default(self) -> None:
        g: Grid2D[int] = Grid2D(2, 2, default_factory=int)
        self.assertIsNone(g.get(5, 5))
        self.assertEqual(g.get(-1, 0, -99), -99)

    def test_set_out_of_bounds_raises(self) -> None:
        g: Grid2D[int] = Grid2D(2, 2, default_factory=int)
        with self.assertRaises(IndexError):
            g.set(2, 0, 1)
        with self.assertRaises(IndexError):
            g.set(0, 2, 1)
        with self.assertRaises(IndexError):
            g.set(-1, 0, 1)


class IterationTests(unittest.TestCase):
    def test_iteration_covers_all_cells(self) -> None:
        g: Grid2D[int] = Grid2D(3, 2, default_factory=int)
        coords = {coord for coord, _ in g}
        expected = {(x, y) for x in range(3) for y in range(2)}
        self.assertEqual(coords, expected)

    def test_iteration_order_x_then_y(self) -> None:
        """Iteration is column-major (x changes, then y within each x)."""
        g: Grid2D[int] = Grid2D(2, 3, default_factory=int)
        coords = [coord for coord, _ in g]
        self.assertEqual(coords[0], (0, 0))
        self.assertEqual(coords[1], (0, 1))
        self.assertEqual(coords[2], (0, 2))
        self.assertEqual(coords[3], (1, 0))


class FillTests(unittest.TestCase):
    def test_fill_replaces_all_cells(self) -> None:
        g: Grid2D[int] = Grid2D(2, 2, default_factory=int)
        g.fill(lambda: 7)
        for _, v in g:
            self.assertEqual(v, 7)

    def test_fill_factory_called_per_cell_no_sharing(self) -> None:
        g: Grid2D[list] = Grid2D(2, 2, default_factory=list)
        g.fill(list)
        g.get(0, 0).append(1)  # type: ignore[union-attr]
        self.assertEqual(g.get(1, 0), [])


class CropTests(unittest.TestCase):
    def test_crop_returns_correct_subregion(self) -> None:
        data = [[y + x * 3 for y in range(3)] for x in range(4)]
        g: Grid2D[int] = Grid2D(4, 3, data=data)
        cropped = g.crop(1, 0, 2, 2)
        self.assertEqual(cropped.width, 2)
        self.assertEqual(cropped.height, 2)
        self.assertEqual(cropped.get(0, 0), g.get(1, 0))
        self.assertEqual(cropped.get(1, 1), g.get(2, 1))

    def test_crop_touching_right_boundary(self) -> None:
        g: Grid2D[int] = Grid2D(4, 3, default_factory=int)
        cropped = g.crop(2, 0, 2, 3)
        self.assertEqual(cropped.width, 2)

    def test_crop_out_of_bounds_raises(self) -> None:
        g: Grid2D[int] = Grid2D(3, 3, default_factory=int)
        with self.assertRaises(ValueError):
            g.crop(2, 0, 2, 3)

    def test_crop_zero_size_raises(self) -> None:
        g: Grid2D[int] = Grid2D(3, 3, default_factory=int)
        with self.assertRaises(ValueError):
            g.crop(0, 0, 0, 1)


class PasteTests(unittest.TestCase):
    def test_paste_copies_source_into_dest(self) -> None:
        src = Grid2D(2, 2, data=[[1, 2], [3, 4]])
        dst = Grid2D(4, 4, default_factory=int)
        dst.paste(src, 1, 1)
        self.assertEqual(dst.get(1, 1), 1)
        self.assertEqual(dst.get(2, 2), 4)

    def test_paste_out_of_bounds_raises_without_clip(self) -> None:
        src = Grid2D(2, 2, default_factory=lambda: 1)
        dst = Grid2D(3, 3, default_factory=int)
        with self.assertRaises(ValueError):
            dst.paste(src, 2, 2)

    def test_paste_with_clip_skips_out_of_bounds(self) -> None:
        src = Grid2D(3, 3, data=[[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        dst = Grid2D(2, 2, default_factory=int)
        dst.paste(src, 0, 0, clip=True)
        self.assertEqual(dst.get(0, 0), 1)
        self.assertEqual(dst.get(1, 1), 5)

    def test_paste_does_not_mutate_source(self) -> None:
        src = Grid2D(1, 1, data=[[42]])
        dst = Grid2D(2, 2, default_factory=int)
        dst.paste(src, 0, 0)
        dst.set(0, 0, 99)
        self.assertEqual(src.get(0, 0), 42)

    def test_paste_with_clip_negative_offset_skips_out_of_bounds(self) -> None:
        dst = Grid2D(3, 3, default_factory=int)
        src = Grid2D(2, 2, default_factory=lambda: 9)

        dst.paste(src, -1, -1, clip=True)

        self.assertEqual(dst.get(0, 0), 9)
        self.assertEqual(dst.get(1, 0), 0)
        self.assertEqual(dst.get(0, 1), 0)


class Grid2DExtensionTests(unittest.TestCase):
    def test_add_margin_increases_size_and_offsets_content(self) -> None:
        grid = Grid2D(1, 1, default_factory=int)
        grid.set(0, 0, 7)

        expanded = grid.add_margin(top=0, right=0, bottom=1, left=1)

        self.assertEqual((expanded.width, expanded.height), (2, 2))
        self.assertEqual(expanded.get(1, 1), 7)

    def test_add_margin_rejects_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(1, 1).add_margin(left=-1)

    def test_to_from_string_round_trip(self) -> None:
        grid = Grid2D(3, 2, default_factory=int)
        grid.set(0, 0, 1)
        grid.set(1, 1, 5)

        encoded = grid.to_string(str, separator=",", row_separator="|")
        restored = Grid2D.from_string(encoded, int, separator=",", row_separator="|")

        self.assertEqual((restored.width, restored.height), (3, 2))
        self.assertEqual(restored.get(1, 1), 5)

    def test_sample_bilinear_interpolates_numeric_cells(self) -> None:
        grid = Grid2D(2, 2, data=[[0.0, 0.0], [1.0, 1.0]])

        self.assertAlmostEqual(grid.sample_bilinear(0.5, 0.0), 0.5)
        self.assertAlmostEqual(grid.sample_bilinear(0.5, 0.5), 0.5)

    def test_sample_bilinear_rejects_out_of_bounds(self) -> None:
        with self.assertRaises(ValueError):
            Grid2D(2, 2, default_factory=float).sample_bilinear(-0.1, 0.0)


class CopyTests(unittest.TestCase):
    def test_copy_is_independent(self) -> None:
        g: Grid2D[int] = Grid2D(2, 2, data=[[1, 2], [3, 4]])
        g2 = g.copy()
        g2.set(0, 0, 99)
        self.assertEqual(g.get(0, 0), 1)

    def test_repr(self) -> None:
        g = Grid2D(5, 7)
        self.assertIn("5", repr(g))
        self.assertIn("7", repr(g))


if __name__ == "__main__":
    unittest.main()
