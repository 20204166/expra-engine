"""Renderer-neutral tilemap coordinates and autotile metadata."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = ("TileCoordinate", "TileData", "TileMap")


@dataclass(frozen=True, order=True)
class TileCoordinate:
    """An immutable, integer tile coordinate."""

    x: int
    y: int


@dataclass(frozen=True)
class TileData:
    """Data a renderer may use to display one generated tile."""

    coordinate: TileCoordinate
    layer: str
    neighbor_mask: int
    variation: int


class TileMap:
    """A bounded collection of independent, named tile layers."""

    _NEIGHBOR_OFFSETS = (
        (0, 1),
        (1, 1),
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, -1),
        (-1, 0),
        (-1, 1),
    )

    def __init__(
        self,
        width: int,
        height: int,
        layers: Mapping[str, Iterable[TileCoordinate | tuple[int, int]]] | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("tilemap dimensions must be positive")
        self.width = width
        self.height = height
        self._layers = {
            name: frozenset(self._coordinate(coordinate) for coordinate in coordinates)
            for name, coordinates in (layers or {}).items()
        }
        for coordinates in self._layers.values():
            if any(not self.contains(coordinate) for coordinate in coordinates):
                raise ValueError("tile coordinates must be within tilemap bounds")

    def contains(self, coordinate: TileCoordinate | tuple[int, int]) -> bool:
        """Return whether ``coordinate`` is inside the map bounds."""
        tile = self._coordinate(coordinate)
        return 0 <= tile.x < self.width and 0 <= tile.y < self.height

    def neighbor_mask(self, layer: str, coordinate: TileCoordinate | tuple[int, int]) -> int:
        """Return clockwise occupancy bits, beginning at the top neighbor."""
        tile = self._coordinate(coordinate)
        if not self.contains(tile):
            raise ValueError("tile coordinate is outside tilemap bounds")
        occupied = self._layers[layer]
        mask = 0
        for bit, (dx, dy) in enumerate(self._NEIGHBOR_OFFSETS):
            neighbor = TileCoordinate(tile.x + dx, tile.y + dy)
            if self.contains(neighbor) and neighbor in occupied:
                mask |= 1 << bit
        return mask

    def generate(self, layer: str, *, seed: int = 0, variation_count: int = 1) -> tuple[TileData, ...]:
        """Generate stable tile data using a local random stream."""
        if variation_count <= 0:
            raise ValueError("variation_count must be positive")
        rng = random.Random(seed)
        return tuple(
            TileData(tile, layer, self.neighbor_mask(layer, tile), rng.randrange(variation_count))
            for tile in sorted(self._layers[layer])
        )

    @staticmethod
    def _coordinate(coordinate: TileCoordinate | tuple[int, int]) -> TileCoordinate:
        if isinstance(coordinate, TileCoordinate):
            return coordinate
        return TileCoordinate(int(coordinate[0]), int(coordinate[1]))
