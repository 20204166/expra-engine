"""Camera2D — world-space / screen-space coordinate math.

Adapted from ppb/camera.py (PursuedPyBear, Artistic License 2.0).

Key preserved semantics (see ppb/tests/test_camera.py for the original
property-test coverage):
  - pixel_ratio = viewport_pixels / game_units
  - translate_to_screen: game-space point → pixel coords
  - translate_to_game: pixel coords → game-space point
  - width / height settable via either dimension; other adjusts to aspect ratio
  - point_is_visible: inclusive boundary check
  - left / right / top / bottom: world-space edges of the viewport frame

Expra-specific differences from PPB Camera:
  - No dependency on ppb_vector, SDL, or Renderer
  - Uses plain (x, y) float tuples instead of ppb_vector.Vector
  - No pygame/SDL integration
  - Standalone dataclass-like object; not a scene GameObject
  - translate_to_screen / translate_to_game are pure math (no pygame rounding)
  - Raises TypeError on non-numeric point arguments (same validation as PPB)

Coordinate convention (same as PPB):
  - game space: y increases upward
  - screen space: y increases downward (pixel coordinates)
"""

from __future__ import annotations

__all__ = ("Camera2D",)

Vec2 = tuple[float, float]


class Camera2D:
    """2D camera: owns world↔screen coordinate conversion.

    ``position`` is the world-space centre of the viewport.

    Creating a camera::

        cam = Camera2D(position=(0.0, 0.0), target_width=10.0,
                       viewport=(800, 600))

    Game units visible on screen::

        print(cam.width, cam.height)   # 10.0, 7.5

    Convert world point to screen pixel::

        cam.translate_to_screen((3.0, -1.0))

    Convert screen pixel back to world::

        cam.translate_to_game((400, 300))

    Check visibility::

        cam.point_is_visible((0.0, 0.0))

    The camera width/height can be changed at any time::

        cam.width = 20.0   # zoom out; height adjusts automatically
    """

    def __init__(
        self,
        *,
        position: Vec2 = (0.0, 0.0),
        target_width: float = 10.0,
        viewport: tuple[int, int] = (800, 600),
    ) -> None:
        """
        :param position: World-space centre of the viewport (x, y).
        :param target_width: Desired number of game units across the viewport.
        :param viewport: Screen dimensions (width_px, height_px).
        """
        if target_width <= 0:
            raise ValueError(f"target_width must be positive, got {target_width!r}")
        vw, vh = viewport
        if vw <= 0 or vh <= 0:
            raise ValueError(f"viewport dimensions must be positive, got {viewport!r}")

        self._position: Vec2 = (float(position[0]), float(position[1]))
        self._viewport: tuple[int, int] = (vw, vh)
        self._pixel_ratio: float = 0.0
        self._width: float = 0.0
        self._height: float = 0.0
        self._set_dimensions(target_width=target_width)

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------

    @property
    def position(self) -> Vec2:
        """World-space centre of the viewport."""
        return self._position

    @position.setter
    def position(self, value: Vec2) -> None:
        self._position = (float(value[0]), float(value[1]))

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    @property
    def pixel_ratio(self) -> float:
        """Pixels per game unit."""
        return self._pixel_ratio

    @property
    def width(self) -> float:
        """Game-unit width of the visible viewport."""
        return self._width

    @width.setter
    def width(self, target_width: float) -> None:
        self._set_dimensions(target_width=float(target_width))

    @property
    def height(self) -> float:
        """Game-unit height of the visible viewport."""
        return self._height

    @height.setter
    def height(self, target_height: float) -> None:
        self._set_dimensions(target_height=float(target_height))

    # ------------------------------------------------------------------
    # Viewport edges (world-space)
    # ------------------------------------------------------------------

    @property
    def left(self) -> float:
        return self._position[0] - self._width / 2

    @property
    def right(self) -> float:
        return self._position[0] + self._width / 2

    @property
    def top(self) -> float:
        return self._position[1] + self._height / 2

    @property
    def bottom(self) -> float:
        return self._position[1] - self._height / 2

    @property
    def top_left(self) -> Vec2:
        return (self.left, self.top)

    @property
    def top_right(self) -> Vec2:
        return (self.right, self.top)

    @property
    def bottom_left(self) -> Vec2:
        return (self.left, self.bottom)

    @property
    def bottom_right(self) -> Vec2:
        return (self.right, self.bottom)

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def point_is_visible(self, point: Vec2) -> bool:
        """Return True if ``point`` (world-space) is within the viewport.

        Points on the boundary are considered visible (inclusive).
        """
        x, y = self._coerce_vec2(point)
        return self.left <= x <= self.right and self.bottom <= y <= self.top

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def translate_to_screen(self, point: Vec2) -> tuple[float, float]:
        """Convert a world-space point to screen-pixel coordinates.

        Screen origin is top-left; y increases downward.

        Raises TypeError if ``point`` does not have numeric x/y attributes
        or indexable components.
        """
        x, y = self._coerce_vec2(point)
        px = (x - self.left) * self._pixel_ratio
        py = (self.top - y) * self._pixel_ratio
        return (px, py)

    def translate_to_game(self, point: Vec2) -> tuple[float, float]:
        """Convert screen-pixel coordinates to world-space.

        Inverse of translate_to_screen.
        """
        px, py = self._coerce_vec2(point)
        x = self.left + px / self._pixel_ratio
        y = self.top - py / self._pixel_ratio
        return (x, y)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_dimensions(
        self,
        target_width: float | None = None,
        target_height: float | None = None,
    ) -> None:
        if target_width is not None and target_height is not None:
            raise ValueError("Cannot set both target_width and target_height simultaneously")
        if target_width is None and target_height is None:
            raise ValueError("Must supply target_width or target_height")

        vw, vh = self._viewport
        if target_width is not None:
            self._pixel_ratio = vw / target_width
        else:
            assert target_height is not None
            self._pixel_ratio = vh / target_height

        self._width = vw / self._pixel_ratio
        self._height = vh / self._pixel_ratio

    @staticmethod
    def _coerce_vec2(point: object) -> tuple[float, float]:
        """Extract (x, y) floats from a point-like object or raise TypeError."""
        # Reject bare strings — they're indexable but not points
        if isinstance(point, (str, bytes)):
            raise TypeError(
                f"Expected a (x, y) tuple or object with .x/.y, got {type(point).__name__}: {point!r}"
            )
        try:
            x = float(point[0])  # type: ignore[index]
            y = float(point[1])  # type: ignore[index]
            return x, y
        except (TypeError, KeyError, IndexError, ValueError):
            pass
        try:
            x = float(point.x)  # type: ignore[attr-defined]
            y = float(point.y)  # type: ignore[attr-defined]
            return x, y
        except (TypeError, AttributeError):
            pass
        raise TypeError(
            f"Expected a (x, y) tuple or object with .x/.y, got {type(point).__name__}: {point!r}"
        )

    def __repr__(self) -> str:
        return (
            f"Camera2D(pos={self._position!r}, "
            f"viewport={self._viewport!r}, "
            f"game_units={self._width:.2f}x{self._height:.2f})"
        )
