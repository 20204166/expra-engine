"""Bounded uniform-grid broadphase for immutable 2D bounds."""

from __future__ import annotations

import math
from collections.abc import Iterable

Bounds2D = tuple[float, float, float, float]


class SpatialIndex2D[SpatialKey]:
    """Return conservative bounds candidates in their original insertion order.

    Oversized entries are kept in a small global list instead of being copied
    into an unbounded number of grid cells. Pathologically large queries fall
    back to all keys, preserving correctness without enumerating huge ranges.
    """

    def __init__(
        self,
        entries: Iterable[tuple[SpatialKey, Bounds2D]],
        *,
        cell_size: float = 8.0,
        max_cells_per_entry: int = 64,
        max_query_cells: int = 65_536,
    ) -> None:
        if not math.isfinite(cell_size) or cell_size <= 0.0:
            raise ValueError("cell_size must be finite and positive")
        if max_cells_per_entry <= 0 or max_query_cells <= 0:
            raise ValueError("spatial cell limits must be positive")

        self._cell_size = cell_size
        self._max_cells_per_entry = max_cells_per_entry
        self._max_query_cells = max_query_cells
        self._keys: list[SpatialKey] = []
        self._bounds: list[Bounds2D] = []
        self._cells: dict[tuple[int, int], list[int]] = {}
        self._global: set[int] = set()
        self._ordinal_by_key: dict[SpatialKey, int] = {}
        self._entry_cells: list[tuple[tuple[int, int], ...] | None] = []
        self._cell_reference_count = 0
        for key, raw_bounds in entries:
            if key in self._ordinal_by_key:
                raise ValueError("spatial index keys must be unique")
            bounds = self._validated_bounds(raw_bounds)
            ordinal = len(self._keys)
            self._keys.append(key)
            self._bounds.append(bounds)
            self._ordinal_by_key[key] = ordinal
            self._entry_cells.append(None)
            self._insert_ordinal(ordinal)

    @property
    def entry_count(self) -> int:
        return len(self._keys)

    @property
    def cell_count(self) -> int:
        return len(self._cells)

    @property
    def cell_reference_count(self) -> int:
        return self._cell_reference_count

    @property
    def overflow_entry_count(self) -> int:
        return len(self._global)

    def query(self, raw_bounds: Bounds2D) -> tuple[SpatialKey, ...]:
        """Return a stable, conservative set of entries intersecting bounds."""
        bounds = self._validated_bounds(raw_bounds)
        cell_range = self._cell_range(bounds)
        x_count = cell_range[1] - cell_range[0] + 1
        y_count = cell_range[3] - cell_range[2] + 1
        if x_count * y_count > self._max_query_cells:
            return tuple(self._keys)

        candidates: set[int] = set()
        for ordinal in self._global:
            if self._intersects(self._bounds[ordinal], bounds):
                candidates.add(ordinal)
        for cell_x in range(cell_range[0], cell_range[1] + 1):
            for cell_y in range(cell_range[2], cell_range[3] + 1):
                candidates.update(self._cells.get((cell_x, cell_y), ()))
        return tuple(self._keys[ordinal] for ordinal in sorted(candidates))

    def update(self, key: SpatialKey, raw_bounds: Bounds2D) -> None:
        """Move one indexed entry without rebuilding unrelated cell membership."""
        ordinal = self._ordinal_by_key.get(key)
        if ordinal is None:
            raise KeyError(key)
        bounds = self._validated_bounds(raw_bounds)
        old_cells = self._entry_cells[ordinal]
        if old_cells is None:
            self._global.discard(ordinal)
        else:
            for cell in old_cells:
                ordinals = self._cells[cell]
                ordinals.remove(ordinal)
                self._cell_reference_count -= 1
                if not ordinals:
                    del self._cells[cell]
        self._bounds[ordinal] = bounds
        self._entry_cells[ordinal] = None
        self._insert_ordinal(ordinal)

    def _insert_ordinal(self, ordinal: int) -> None:
        cell_range = self._cell_range(self._bounds[ordinal])
        x_count = cell_range[1] - cell_range[0] + 1
        y_count = cell_range[3] - cell_range[2] + 1
        if x_count * y_count > self._max_cells_per_entry:
            self._global.add(ordinal)
            self._entry_cells[ordinal] = None
            return
        cells: list[tuple[int, int]] = []
        for cell_x in range(cell_range[0], cell_range[1] + 1):
            for cell_y in range(cell_range[2], cell_range[3] + 1):
                cell = (cell_x, cell_y)
                self._cells.setdefault(cell, []).append(ordinal)
                self._cell_reference_count += 1
                cells.append(cell)
        self._entry_cells[ordinal] = tuple(cells)

    def _cell_range(self, bounds: Bounds2D) -> tuple[int, int, int, int]:
        left, top, right, bottom = bounds
        return (
            math.floor(left / self._cell_size),
            math.floor(right / self._cell_size),
            math.floor(top / self._cell_size),
            math.floor(bottom / self._cell_size),
        )

    @staticmethod
    def _validated_bounds(bounds: Bounds2D) -> Bounds2D:
        if len(bounds) != 4:
            raise ValueError("bounds must contain left, top, right, bottom")
        left, top, right, bottom = (float(value) for value in bounds)
        if not all(math.isfinite(value) for value in (left, top, right, bottom)):
            raise ValueError("bounds must be finite")
        if left > right or top > bottom:
            raise ValueError("bounds minimums must not exceed maximums")
        return left, top, right, bottom

    @staticmethod
    def _intersects(first: Bounds2D, second: Bounds2D) -> bool:
        return (
            first[0] <= second[2]
            and first[2] >= second[0]
            and first[1] <= second[3]
            and first[3] >= second[1]
        )
