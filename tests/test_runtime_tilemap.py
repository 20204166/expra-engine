"""Tests for renderer-neutral tilemap data and autotile metadata."""

import random
import unittest
from dataclasses import FrozenInstanceError

from expra_engine.runtime.tilemap import TileCoordinate, TileData, TileMap


class TestTileMapBoundsAndLayers(unittest.TestCase):
    def test_empty_and_one_cell_maps_generate_expected_data(self) -> None:
        empty = TileMap(2, 2, {"ground": ()})
        self.assertEqual(empty.generate("ground"), ())

        one_cell = TileMap(1, 1, {"ground": ((0, 0),)})
        generated = one_cell.generate("ground")
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].coordinate, TileCoordinate(0, 0))
        self.assertEqual(generated[0].neighbor_mask, 0)

    def test_negative_and_out_of_range_coordinates_are_rejected(self) -> None:
        tilemap = TileMap(2, 2, {"ground": ((0, 0),)})

        self.assertFalse(tilemap.contains((-1, 0)))
        self.assertFalse(tilemap.contains((2, 0)))
        for coordinate in ((-1, 0), (0, 2)):
            with self.subTest(coordinate=coordinate), self.assertRaises(ValueError):
                tilemap.neighbor_mask("ground", coordinate)
        with self.assertRaises(ValueError):
            TileMap(2, 2, {"ground": ((2, 0),)})

    def test_dimensions_must_be_positive(self) -> None:
        for dimensions in ((0, 1), (1, 0), (-1, 1)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                TileMap(*dimensions)

    def test_coordinates_are_immutable(self) -> None:
        coordinate = TileCoordinate(1, 2)

        with self.assertRaises(FrozenInstanceError):
            coordinate.x = 3  # type: ignore[misc]


class TestTileMapNeighborMasks(unittest.TestCase):
    def test_corner_and_edge_masks_use_clockwise_eight_neighbor_bits(self) -> None:
        tilemap = TileMap(
            3,
            3,
            {
                "ground": ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0)),
            },
        )

        # Bits are top, top-right, right, bottom-right, bottom, bottom-left,
        # left, top-left. Out-of-bounds neighbors are absent.
        self.assertEqual(tilemap.neighbor_mask("ground", (0, 0)), 0b00000111)
        self.assertEqual(tilemap.neighbor_mask("ground", (1, 0)), 0b11000101)

    def test_layers_do_not_contribute_to_each_others_masks(self) -> None:
        tilemap = TileMap(2, 1, {"ground": ((0, 0),), "water": ((1, 0),)})

        self.assertEqual(tilemap.neighbor_mask("ground", (0, 0)), 0)
        self.assertEqual(tilemap.neighbor_mask("water", (1, 0)), 0)
        self.assertEqual(tilemap.generate("ground")[0].layer, "ground")


class TestTileMapGeneration(unittest.TestCase):
    def test_repeated_generation_is_stable_and_variation_is_seeded_locally(self) -> None:
        tilemap = TileMap(4, 1, {"ground": ((0, 0), (1, 0), (2, 0), (3, 0))})
        random.seed(1234)
        before = random.getstate()

        first = tilemap.generate("ground", seed=9, variation_count=5)
        after = random.getstate()
        second = tilemap.generate("ground", seed=9, variation_count=5)

        self.assertEqual(before, after)
        self.assertEqual(first, second)
        self.assertTrue(all(0 <= tile.variation < 5 for tile in first))
        self.assertGreater(len({tile.variation for tile in first}), 1)

    def test_generated_tile_data_is_immutable(self) -> None:
        generated = TileMap(1, 1, {"ground": ((0, 0),)}).generate("ground")[0]

        with self.assertRaises(FrozenInstanceError):
            generated.variation = 2  # type: ignore[misc]

    def test_variation_count_must_be_positive(self) -> None:
        tilemap = TileMap(1, 1, {"ground": ((0, 0),)})

        with self.assertRaises(ValueError):
            tilemap.generate("ground", variation_count=0)

        self.assertIsInstance(tilemap.generate("ground")[0], TileData)


if __name__ == "__main__":
    unittest.main()


class TileMapEdgeTests(unittest.TestCase):
    def test_empty_layer_produces_no_tile_data(self) -> None:
        m = TileMap(5, 5, {"ground": []})
        result = m.generate("ground")
        self.assertEqual(result, ())

    def test_single_tile_isolated_has_zero_neighbor_mask(self) -> None:
        m = TileMap(5, 5, {"ground": [(2, 2)]})
        self.assertEqual(m.neighbor_mask("ground", TileCoordinate(2, 2)), 0)

    def test_fully_surrounded_tile_has_full_mask(self) -> None:
        coords = [(x, y) for x in range(3) for y in range(3)]
        m = TileMap(3, 3, {"g": coords})
        mask = m.neighbor_mask("g", TileCoordinate(1, 1))
        self.assertEqual(mask, 0xFF)

    def test_map_boundary_does_not_count_as_neighbor(self) -> None:
        m = TileMap(3, 3, {"g": [(0, 0), (1, 0), (0, 1)]})
        # Corner tile (0,0): neighbors outside bounds are not counted
        mask = m.neighbor_mask("g", TileCoordinate(0, 0))
        # Only (1,0) and (0,1) can be neighbors; (-1,-1) etc. are out of bounds
        self.assertLess(bin(mask).count("1"), 8)

    def test_generate_is_deterministic_with_same_seed(self) -> None:
        coords = [(x, y) for x in range(3) for y in range(3)]
        m = TileMap(5, 5, {"g": coords})
        r1 = m.generate("g", seed=42, variation_count=4)
        r2 = m.generate("g", seed=42, variation_count=4)
        self.assertEqual([t.variation for t in r1], [t.variation for t in r2])

    def test_different_seeds_produce_different_variations(self) -> None:
        coords = [(x, y) for x in range(4) for y in range(4)]
        m = TileMap(5, 5, {"g": coords})
        r1 = m.generate("g", seed=1, variation_count=100)
        r2 = m.generate("g", seed=2, variation_count=100)
        variations_differ = any(a.variation != b.variation for a, b in zip(r1, r2, strict=False))
        self.assertTrue(variations_differ)

    def test_negative_variation_count_rejected(self) -> None:
        m = TileMap(3, 3, {"g": [(0, 0)]})
        with self.assertRaises(ValueError):
            m.generate("g", variation_count=0)

    def test_out_of_bounds_neighbor_mask_raises(self) -> None:
        m = TileMap(3, 3, {"g": [(1, 1)]})
        with self.assertRaises(ValueError):
            m.neighbor_mask("g", TileCoordinate(5, 5))
