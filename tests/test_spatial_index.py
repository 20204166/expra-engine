from __future__ import annotations

from expra_engine.core.spatial_index import SpatialIndex2D


def test_spatial_index_returns_overlapping_candidates_in_insertion_order() -> None:
    index = SpatialIndex2D(
        (
            ("far", (40.0, 40.0, 41.0, 41.0)),
            ("near-a", (-1.0, -1.0, 1.0, 1.0)),
            ("near-b", (1.0, 0.0, 2.0, 1.0)),
        ),
        cell_size=4.0,
    )

    assert index.query((-0.5, -0.5, 1.5, 1.5)) == ("near-a", "near-b")


def test_spatial_index_uses_global_fallback_for_oversized_entries() -> None:
    index = SpatialIndex2D(
        (
            ("oversized", (-1000.0, -1000.0, 1000.0, 1000.0)),
            ("local", (2.0, 2.0, 3.0, 3.0)),
        ),
        cell_size=1.0,
        max_cells_per_entry=4,
    )

    assert index.query((2.0, 2.0, 2.5, 2.5)) == ("oversized", "local")
    assert index.query((1100.0, 1100.0, 1101.0, 1101.0)) == ()


def test_spatial_index_falls_back_to_all_entries_for_huge_queries() -> None:
    index = SpatialIndex2D(
        (("a", (0.0, 0.0, 1.0, 1.0)), ("b", (100.0, 100.0, 101.0, 101.0))),
        cell_size=1.0,
        max_query_cells=4,
    )

    assert index.query((-100.0, -100.0, 200.0, 200.0)) == ("a", "b")


def test_spatial_index_updates_one_entry_without_rebuilding_other_memberships() -> None:
    index = SpatialIndex2D(
        (("moving", (0.0, 0.0, 1.0, 1.0)), ("stable", (40.0, 40.0, 41.0, 41.0))),
        cell_size=4.0,
    )

    index.update("moving", (100.0, 100.0, 101.0, 101.0))

    assert index.query((-1.0, -1.0, 2.0, 2.0)) == ()
    assert index.query((99.0, 99.0, 102.0, 102.0)) == ("moving",)
    assert index.query((39.0, 39.0, 42.0, 42.0)) == ("stable",)
