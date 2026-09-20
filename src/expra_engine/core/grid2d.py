"""Typed, bounds-checked 2D grid with explicit coordinate convention.

(0, 0) is bottom-left; x increases right; y increases up.
This is explicit and tested — do not silently use screen-space conventions here.

Inspired by Ursina's Array2D (ursina/array_tools.py) but:
  - Generic typed cells via Grid2D[T]
  - No mutable-default-value sharing: default_factory isolates each cell
  - Strict boundary policy: out-of-bounds get returns a sentinel; set raises
  - Ragged input rejected at construction
  - Negative or zero dimensions rejected
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any, cast

__all__ = ("Grid2D",)


class Grid2D[T]:
    """A fixed-size, homogeneous 2D grid.

    Coordinate convention: (0, 0) = bottom-left; x = column (right); y = row (up).

    Parameters
    ----------
    width, height
        Positive grid dimensions.
    default_factory
        Called once per cell to produce the initial value.  Use a factory
        (e.g., ``list``) to avoid shared mutable defaults.
    data
        Optional pre-filled column-major list[list[T]].  ``data[x][y]``
        is the value at column x, row y.  If supplied, all columns must
        have exactly ``height`` elements.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        default_factory: Callable[[], T] | None = None,
        data: list[list[T]] | None = None,
    ) -> None:
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            raise ValueError(f"Grid2D dimensions must be positive, got ({width}, {height})")

        self._width = width
        self._height = height
        self._factory: Callable[[], T] = (
            default_factory if default_factory is not None else lambda: None  # type: ignore[return-value]
        )

        if data is not None:
            if len(data) != width:
                raise ValueError(f"data has {len(data)} columns; expected {width}")
            for col_index, col in enumerate(data):
                if len(col) != height:
                    raise ValueError(
                        f"column {col_index} has {len(col)} rows; expected {height} (ragged data rejected)"
                    )
            self._cells: list[list[T]] = [list(col) for col in data]
        else:
            self._cells = [[self._factory() for _ in range(height)] for _ in range(width)]

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def _check(self, x: int, y: int) -> None:
        if not (0 <= x < self._width and 0 <= y < self._height):
            raise IndexError(f"({x}, {y}) is outside Grid2D bounds ({self._width}x{self._height})")

    def get(self, x: int, y: int, default: T | None = None) -> T | None:
        """Return the cell value, or *default* when out of bounds."""
        if not (0 <= x < self._width and 0 <= y < self._height):
            return default
        return self._cells[x][y]

    def set(self, x: int, y: int, value: T) -> None:
        """Set a cell value. Raises IndexError for out-of-bounds coordinates."""
        self._check(x, y)
        self._cells[x][y] = value

    def fill(self, factory: Callable[[], T]) -> None:
        """Replace every cell using *factory* (called once per cell)."""
        for x in range(self._width):
            for y in range(self._height):
                self._cells[x][y] = factory()

    def __iter__(self) -> Iterator[tuple[tuple[int, int], T]]:
        """Iterate left-to-right, bottom-to-top: ((x, y), value)."""
        for x in range(self._width):
            for y in range(self._height):
                yield (x, y), self._cells[x][y]

    def crop(self, x: int, y: int, width: int, height: int) -> Grid2D[T]:
        """Return a new grid containing the specified sub-region.

        Raises ValueError when the region is out of bounds or has invalid size.
        """
        if width <= 0 or height <= 0:
            raise ValueError("crop size must be positive")
        if x < 0 or y < 0 or x + width > self._width or y + height > self._height:
            raise ValueError(
                f"crop ({x},{y})+({width}x{height}) is outside the grid "
                f"({self._width}x{self._height})"
            )
        data = [[self._cells[x + dx][y + dy] for dy in range(height)] for dx in range(width)]
        return Grid2D(width, height, data=data)

    def paste(self, source: Grid2D[T], dest_x: int, dest_y: int, *, clip: bool = False) -> None:
        """Copy *source* cells into this grid at (*dest_x*, *dest_y*).

        If *clip* is True, cells that fall outside this grid are silently
        skipped.  Otherwise, a ValueError is raised for any out-of-bounds
        paste.
        """
        for (sx, sy), value in source:
            tx, ty = dest_x + sx, dest_y + sy
            if not (0 <= tx < self._width and 0 <= ty < self._height):
                if clip:
                    continue
                raise ValueError(
                    f"paste target ({tx}, {ty}) is outside the grid ({self._width}x{self._height})"
                )
            self._cells[tx][ty] = copy.copy(value)

    def copy(self) -> Grid2D[T]:
        """Return a shallow copy with independent cell lists."""
        data = [list(col) for col in self._cells]
        return Grid2D(self._width, self._height, data=data)

    def add_margin(
        self,
        *,
        top: int = 0,
        right: int = 0,
        bottom: int = 0,
        left: int = 0,
    ) -> Grid2D[T]:
        """Return a new grid with empty cells added around this grid."""
        margins = (top, right, bottom, left)
        if any(margin < 0 for margin in margins):
            raise ValueError("margin values must be non-negative")
        result = Grid2D(
            self._width + left + right,
            self._height + top + bottom,
            default_factory=self._factory,
        )
        for (x, y), value in self:
            result.set(x + left, y + bottom, value)
        return result

    def to_string(
        self,
        cell_to_str: Callable[[T], str] = str,
        separator: str = ",",
        row_separator: str = "\n",
    ) -> str:
        """Serialize rows from bottom to top using caller-provided separators."""
        rows = [
            separator.join(cell_to_str(self._cells[x][y]) for x in range(self._width))
            for y in range(self._height)
        ]
        return row_separator.join(rows)

    @classmethod
    def from_string(
        cls,
        text: str,
        str_to_cell: Callable[[str], T] = str,  # type: ignore[assignment]
        separator: str = ",",
        row_separator: str = "\n",
    ) -> Grid2D[T]:
        """Deserialize a row-major string into a bottom-left-origin grid."""
        rows = text.split(row_separator) if text else []
        if not rows or any(row == "" for row in rows):
            raise ValueError("serialized grid must contain non-empty rows")
        values = [[str_to_cell(cell) for cell in row.split(separator)] for row in rows]
        width = len(values[0])
        if width == 0 or any(len(row) != width for row in values):
            raise ValueError("serialized grid must be rectangular")
        data = [[values[y][x] for y in range(len(values))] for x in range(width)]
        return cls(width, len(values), data=data)

    def sample_bilinear(self, x: float, y: float) -> float:
        """Sample numeric cells at fractional coordinates by bilinear blending."""
        if not (0.0 <= x <= self._width - 1 and 0.0 <= y <= self._height - 1):
            raise ValueError("sample coordinates must lie inside the grid")
        x0, y0 = int(x), int(y)
        x1, y1 = min(x0 + 1, self._width - 1), min(y0 + 1, self._height - 1)
        tx, ty = x - x0, y - y0
        v00 = float(cast(Any, self._cells[x0][y0]))
        v10 = float(cast(Any, self._cells[x1][y0]))
        v01 = float(cast(Any, self._cells[x0][y1]))
        v11 = float(cast(Any, self._cells[x1][y1]))
        return float(
            (v00 * (1.0 - tx) + v10 * tx) * (1.0 - ty) + (v01 * (1.0 - tx) + v11 * tx) * ty
        )

    def __repr__(self) -> str:
        return f"Grid2D({self._width}x{self._height})"
