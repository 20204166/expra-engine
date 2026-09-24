"""Camera2D — world-space / screen-space coordinate math and camera motion.

Adapted from ppb/camera.py (PursuedPyBear, Artistic License 2.0).
Camera motion features are adapted from Godot Camera2D concepts while keeping
this module dependency-free and preserving the original Camera2D API.

Preserved semantics:
  - pixel_ratio = viewport_pixels / game_units
  - translate_to_screen: game-space point -> pixel coords
  - translate_to_game: pixel coords -> game-space point
  - width / height settable via either dimension; other adjusts to aspect ratio
  - point_is_visible: inclusive boundary check
  - left / right / top / bottom: world-space edges of the viewport frame

Added camera features:
  - target following via target_position
  - optional position and rotation smoothing
  - horizontal / vertical drag dead-zones
  - world limits
  - camera offset
  - rotation
  - scalar zoom layered over the existing width/height model
  - update(delta) to advance camera motion

Coordinate convention:
  - game space: y increases upward
  - screen space: y increases downward (pixel coordinates)
"""

from __future__ import annotations

import math
from copy import deepcopy

from expra_engine.core.math_utils import lerp_exponential_decay

__all__ = ("Camera2D", "SceneCamera")

Vec2 = tuple[float, float]


class SceneCamera(dict[str, object]):
    """JSON-compatible scene-owned camera configuration."""

    def __init__(self, values: object = None) -> None:
        if values is not None and not isinstance(values, dict):
            raise TypeError("scene camera settings must be an object")
        super().__init__(deepcopy(values) if isinstance(values, dict) else {})

    @property
    def target_entity_id(self) -> str | None:
        value = self.get("target_entity_id")
        return str(value) if value is not None else None

    def to_dict(self) -> dict[str, object]:
        return deepcopy(dict(self))

    def apply_to(self, camera: Camera2D) -> None:
        camera.apply_dict(self)


class Camera2D:
    """Standalone 2D camera with coordinate conversion and optional following.

    Existing use remains valid::

        cam = Camera2D(position=(0, 0), target_width=10, viewport=(800, 600))
        pixel = cam.translate_to_screen((2, 1))

    Following is opt-in::

        cam.target_position = player.position
        cam.position_smoothing_enabled = True
        cam.update(dt)
    """

    def __init__(
        self,
        *,
        position: Vec2 = (0.0, 0.0),
        target_width: float = 10.0,
        viewport: tuple[int, int] = (800, 600),
    ) -> None:
        if target_width <= 0:
            raise ValueError(f"target_width must be positive, got {target_width!r}")
        vw, vh = viewport
        if vw <= 0 or vh <= 0:
            raise ValueError(f"viewport dimensions must be positive, got {viewport!r}")

        pos = self._coerce_vec2(position)
        self._position: Vec2 = pos
        self._target_position: Vec2 = pos
        self._viewport: tuple[int, int] = (vw, vh)
        self._pixel_ratio = 0.0
        self._width = 0.0
        self._height = 0.0
        self._zoom = 1.0

        self._offset: Vec2 = (0.0, 0.0)
        self._rotation = 0.0
        self._target_rotation = 0.0

        self.position_smoothing_enabled = False
        self.position_smoothing_speed = 5.0
        self.rotation_smoothing_enabled = False
        self.rotation_smoothing_speed = 5.0

        self.drag_horizontal_enabled = False
        self.drag_vertical_enabled = False
        self.drag_left_margin = 0.2
        self.drag_top_margin = 0.2
        self.drag_right_margin = 0.2
        self.drag_bottom_margin = 0.2

        self.limit_enabled = False
        self.limit_left = -10_000_000.0
        self.limit_bottom = -10_000_000.0
        self.limit_right = 10_000_000.0
        self.limit_top = 10_000_000.0

        self._set_dimensions(target_width=float(target_width))

    # ------------------------------------------------------------------
    # Position / following
    # ------------------------------------------------------------------

    @property
    def position(self) -> Vec2:
        """Actual world-space centre of the camera."""
        return self._position

    @position.setter
    def position(self, value: Vec2) -> None:
        # Direct assignment remains an immediate move, as in the old camera.
        pos = self._coerce_vec2(value)
        self._position = pos
        self._target_position = pos

    @property
    def target_position(self) -> Vec2:
        """World-space position the camera follows on update()."""
        return self._target_position

    @target_position.setter
    def target_position(self, value: Vec2) -> None:
        self._target_position = self._coerce_vec2(value)

    def reset_smoothing(self) -> None:
        """Snap position and rotation to their current targets."""
        self._position = self._clamp_position(self._target_position)
        self._rotation = self._target_rotation

    # ------------------------------------------------------------------
    # Dimensions / zoom
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
        self._position = self._clamp_position(self._position)

    @property
    def height(self) -> float:
        """Game-unit height of the visible viewport."""
        return self._height

    @height.setter
    def height(self, target_height: float) -> None:
        self._set_dimensions(target_height=float(target_height))
        self._position = self._clamp_position(self._position)

    @property
    def zoom(self) -> float:
        """Scalar zoom. 2.0 shows half as many world units as 1.0."""
        return self._zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        new_zoom = float(value)
        if not math.isfinite(new_zoom) or new_zoom <= 0.0:
            raise ValueError(f"zoom must be finite and positive, got {value!r}")
        if new_zoom == self._zoom:
            return
        # Scale from the current width so width/height remain the source of
        # truth and existing direct dimension setters keep their semantics.
        new_width = self._width * self._zoom / new_zoom
        self._zoom = new_zoom
        self._set_dimensions(target_width=new_width)
        self._position = self._clamp_position(self._position)

    # ------------------------------------------------------------------
    # Offset / rotation
    # ------------------------------------------------------------------

    @property
    def offset(self) -> Vec2:
        """World-space offset applied to the rendered camera centre."""
        return self._offset

    @offset.setter
    def offset(self, value: Vec2) -> None:
        self._offset = self._coerce_vec2(value)
        self._position = self._clamp_position(self._position)

    @property
    def rotation(self) -> float:
        """Actual camera rotation in radians, counter-clockwise in game space."""
        return self._rotation

    @rotation.setter
    def rotation(self, value: float) -> None:
        angle = self._coerce_finite(value, "rotation")
        self._rotation = angle
        self._target_rotation = angle

    @property
    def target_rotation(self) -> float:
        """Rotation target used by update() when rotation smoothing is enabled."""
        return self._target_rotation

    @target_rotation.setter
    def target_rotation(self, value: float) -> None:
        self._target_rotation = self._coerce_finite(value, "target_rotation")

    # ------------------------------------------------------------------
    # Viewport edges (world-space, unrotated frame)
    # ------------------------------------------------------------------

    @property
    def _view_center(self) -> Vec2:
        return (
            self._position[0] + self._offset[0],
            self._position[1] + self._offset[1],
        )

    @property
    def left(self) -> float:
        return self._view_center[0] - self._width / 2

    @property
    def right(self) -> float:
        return self._view_center[0] + self._width / 2

    @property
    def top(self) -> float:
        return self._view_center[1] + self._height / 2

    @property
    def bottom(self) -> float:
        return self._view_center[1] - self._height / 2

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
    # Visibility / coordinate conversion
    # ------------------------------------------------------------------

    def point_is_visible(self, point: Vec2) -> bool:
        """Return True when a world point lies inside the current view."""
        x, y = self._coerce_vec2(point)
        if not self._rotation:
            # Preserve the original camera's exact inclusive edge semantics.
            return self.left <= x <= self.right and self.bottom <= y <= self.top
        px, py = self.translate_to_screen((x, y))
        vw, vh = self._viewport
        return 0.0 <= px <= vw and 0.0 <= py <= vh

    def translate_to_screen(self, point: Vec2) -> tuple[float, float]:
        """Convert a world-space point to top-left-origin screen pixels."""
        x, y = self._coerce_vec2(point)
        if not self._rotation:
            # Same operation order as the original implementation.
            return (
                (x - self.left) * self._pixel_ratio,
                (self.top - y) * self._pixel_ratio,
            )

        cx, cy = self._view_center
        dx, dy = x - cx, y - cy
        c = math.cos(self._rotation)
        s = math.sin(self._rotation)
        dx, dy = c * dx + s * dy, -s * dx + c * dy
        vw, vh = self._viewport
        return (
            vw * 0.5 + dx * self._pixel_ratio,
            vh * 0.5 - dy * self._pixel_ratio,
        )

    def translate_to_game(self, point: Vec2) -> tuple[float, float]:
        """Convert screen pixels back to world-space."""
        px, py = self._coerce_vec2(point)
        if not self._rotation:
            # Same operation order as the original implementation.
            return (
                self.left + px / self._pixel_ratio,
                self.top - py / self._pixel_ratio,
            )

        vw, vh = self._viewport
        dx = (px - vw * 0.5) / self._pixel_ratio
        dy = (vh * 0.5 - py) / self._pixel_ratio
        c = math.cos(self._rotation)
        s = math.sin(self._rotation)
        dx, dy = c * dx - s * dy, s * dx + c * dy
        cx, cy = self._view_center
        return (cx + dx, cy + dy)

    def project(self, point: Vec2, viewport: object) -> tuple[float, float]:
        """Project a world point into an arbitrary pixel viewport."""
        x, y = self._coerce_vec2(point)
        viewport_x = float(viewport.x)  # type: ignore[attr-defined]
        viewport_y = float(viewport.y)  # type: ignore[attr-defined]
        viewport_width = float(viewport.width)  # type: ignore[attr-defined]
        viewport_height = float(viewport.height)  # type: ignore[attr-defined]
        if not self._rotation:
            return (
                viewport_x + (x - self.left) / self._width * viewport_width,
                viewport_y + (self.top - y) / self._height * viewport_height,
            )

        cx, cy = self._view_center
        dx, dy = x - cx, y - cy
        c = math.cos(self._rotation)
        s = math.sin(self._rotation)
        rotated_x, rotated_y = c * dx + s * dy, -s * dx + c * dy
        return (
            viewport_x + viewport_width * 0.5 + rotated_x / self._width * viewport_width,
            viewport_y + viewport_height * 0.5 - rotated_y / self._height * viewport_height,
        )

    def unproject(self, point: Vec2, viewport: object) -> Vec2:
        """Convert a point from an arbitrary pixel viewport into world space."""
        px, py = self._coerce_vec2(point)
        viewport_x = float(viewport.x)  # type: ignore[attr-defined]
        viewport_y = float(viewport.y)  # type: ignore[attr-defined]
        viewport_width = float(viewport.width)  # type: ignore[attr-defined]
        viewport_height = float(viewport.height)  # type: ignore[attr-defined]
        if not self._rotation:
            return (
                self.left + (px - viewport_x) / viewport_width * self._width,
                self.top - (py - viewport_y) / viewport_height * self._height,
            )

        rotated_x = (px - viewport_x - viewport_width * 0.5) / viewport_width * self._width
        rotated_y = (viewport_y + viewport_height * 0.5 - py) / viewport_height * self._height
        c = math.cos(self._rotation)
        s = math.sin(self._rotation)
        dx, dy = c * rotated_x - s * rotated_y, s * rotated_x + c * rotated_y
        cx, cy = self._view_center
        return (cx + dx, cy + dy)

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe camera settings for scene or editor persistence."""
        values: dict[str, object] = {
            "position": list(self.position),
            "target_position": list(self.target_position),
            "width": self.width,
            "zoom": self.zoom,
            "offset": list(self.offset),
            "rotation": self.rotation,
            "target_rotation": self.target_rotation,
            "position_smoothing_enabled": self.position_smoothing_enabled,
            "position_smoothing_speed": self.position_smoothing_speed,
            "rotation_smoothing_enabled": self.rotation_smoothing_enabled,
            "rotation_smoothing_speed": self.rotation_smoothing_speed,
            "drag_horizontal_enabled": self.drag_horizontal_enabled,
            "drag_vertical_enabled": self.drag_vertical_enabled,
            "drag_margins": list(self.drag_margins),
            "limit_enabled": self.limit_enabled,
            "limits": [self.limit_left, self.limit_bottom, self.limit_right, self.limit_top],
        }
        if hasattr(self, "near"):
            values["near"] = self.near  # type: ignore[attr-defined]
            values["far"] = self.far  # type: ignore[attr-defined]
        return values

    def apply_dict(self, values: object) -> None:
        """Apply persisted camera settings, ignoring unknown future keys."""
        if not isinstance(values, dict):
            raise TypeError("camera settings must be an object")
        if "position" in values:
            self.position = values["position"]  # type: ignore[assignment]
        if "width" in values:
            self.width = values["width"]  # type: ignore[arg-type]
        if "zoom" in values:
            self.zoom = values["zoom"]  # type: ignore[arg-type]
        for name in ("offset", "rotation", "target_rotation", "target_position"):
            if name in values:
                setattr(self, name, values[name])
        for name in (
            "position_smoothing_enabled",
            "position_smoothing_speed",
            "rotation_smoothing_enabled",
            "rotation_smoothing_speed",
            "drag_horizontal_enabled",
            "drag_vertical_enabled",
        ):
            if name in values:
                setattr(self, name, values[name])
        if "drag_margins" in values:
            self.drag_margins = values["drag_margins"]  # type: ignore[assignment]
        limits = values.get("limits")
        if values.get("limit_enabled") and limits is not None:
            self.set_limits(*limits)  # type: ignore[arg-type]
        elif values.get("limit_enabled") is False:
            self.clear_limits()

    # ------------------------------------------------------------------
    # Drag / dead-zone
    # ------------------------------------------------------------------

    @property
    def drag_margins(self) -> tuple[float, float, float, float]:
        """Dead-zone fractions as (left, top, right, bottom)."""
        return (
            self.drag_left_margin,
            self.drag_top_margin,
            self.drag_right_margin,
            self.drag_bottom_margin,
        )

    @drag_margins.setter
    def drag_margins(self, value: tuple[float, float, float, float]) -> None:
        if len(value) != 4:
            raise ValueError("drag_margins must contain left, top, right, bottom")
        margins = tuple(self._coerce_margin(v) for v in value)
        (
            self.drag_left_margin,
            self.drag_top_margin,
            self.drag_right_margin,
            self.drag_bottom_margin,
        ) = margins

    # ------------------------------------------------------------------
    # Limits
    # ------------------------------------------------------------------

    def set_limits(self, left: float, bottom: float, right: float, top: float) -> None:
        """Set world bounds that the unrotated camera frame may not leave."""
        left = self._coerce_finite(left, "left")
        bottom = self._coerce_finite(bottom, "bottom")
        right = self._coerce_finite(right, "right")
        top = self._coerce_finite(top, "top")
        if right < left or top < bottom:
            raise ValueError("limits require right >= left and top >= bottom")
        self.limit_left, self.limit_bottom = left, bottom
        self.limit_right, self.limit_top = right, top
        self.limit_enabled = True
        self._position = self._clamp_position(self._position)

    def clear_limits(self) -> None:
        self.limit_enabled = False

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, delta: float) -> Vec2:
        """Advance following/smoothing by ``delta`` seconds and return position."""
        dt = float(delta)
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError(f"delta must be finite and non-negative, got {delta!r}")

        desired = self._dead_zone_target()

        if self.position_smoothing_enabled and dt > 0.0:
            speed = max(0.0, self._coerce_finite(self.position_smoothing_speed, "position_smoothing_speed"))
            x = lerp_exponential_decay(self._position[0], desired[0], dt, speed)
            y = lerp_exponential_decay(self._position[1], desired[1], dt, speed)
            self._position = self._clamp_position((x, y))
        else:
            self._position = self._clamp_position(desired)

        if self.rotation_smoothing_enabled and dt > 0.0:
            speed = max(0.0, self._coerce_finite(self.rotation_smoothing_speed, "rotation_smoothing_speed"))
            alpha = 1.0 - math.exp(-speed * dt)
            diff = self._wrap_angle(self._target_rotation - self._rotation)
            self._rotation += diff * alpha
        else:
            self._rotation = self._target_rotation

        return self._position

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dead_zone_target(self) -> Vec2:
        tx, ty = self._target_position
        cx, cy = self._position
        half_w, half_h = self._width * 0.5, self._height * 0.5

        if self.drag_horizontal_enabled:
            left_margin = self._coerce_margin(self.drag_left_margin)
            right_margin = self._coerce_margin(self.drag_right_margin)
            left = cx - half_w * left_margin
            right = cx + half_w * right_margin
            if tx < left:
                cx = tx + half_w * left_margin
            elif tx > right:
                cx = tx - half_w * right_margin
        else:
            cx = tx

        if self.drag_vertical_enabled:
            bottom_margin = self._coerce_margin(self.drag_bottom_margin)
            top_margin = self._coerce_margin(self.drag_top_margin)
            bottom = cy - half_h * bottom_margin
            top = cy + half_h * top_margin
            if ty < bottom:
                cy = ty + half_h * bottom_margin
            elif ty > top:
                cy = ty - half_h * top_margin
        else:
            cy = ty

        return self._clamp_position((cx, cy))

    def _clamp_position(self, position: Vec2) -> Vec2:
        x, y = position
        if not self.limit_enabled:
            return (x, y)

        half_w, half_h = self._width * 0.5, self._height * 0.5
        ox, oy = self._offset
        min_x = self.limit_left + half_w - ox
        max_x = self.limit_right - half_w - ox
        min_y = self.limit_bottom + half_h - oy
        max_y = self.limit_top - half_h - oy

        x = (self.limit_left + self.limit_right) * 0.5 - ox if min_x > max_x else min(max(x, min_x), max_x)
        y = (self.limit_bottom + self.limit_top) * 0.5 - oy if min_y > max_y else min(max(y, min_y), max_y)
        return (x, y)

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
            if not math.isfinite(target_width) or target_width <= 0.0:
                raise ValueError(f"target_width must be finite and positive, got {target_width!r}")
            self._pixel_ratio = vw / target_width
        else:
            assert target_height is not None
            if not math.isfinite(target_height) or target_height <= 0.0:
                raise ValueError(
                    f"target_height must be finite and positive, got {target_height!r}"
                )
            self._pixel_ratio = vh / target_height

        self._width = vw / self._pixel_ratio
        self._height = vh / self._pixel_ratio

    @staticmethod
    def _coerce_vec2(point: object) -> Vec2:
        """Extract (x, y) floats from a point-like object or raise TypeError."""
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

    @staticmethod
    def _coerce_finite(value: float, name: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite, got {value!r}")
        return number

    @staticmethod
    def _coerce_margin(value: float) -> float:
        margin = float(value)
        if not math.isfinite(margin) or not 0.0 <= margin <= 1.0:
            raise ValueError(f"drag margin must be between 0 and 1, got {value!r}")
        return margin

    @staticmethod
    def _wrap_angle(angle: float) -> float:
        return (angle + math.pi) % (2.0 * math.pi) - math.pi

    def __repr__(self) -> str:
        # Intentionally preserved from the original camera implementation.
        return (
            f"Camera2D(pos={self._position!r}, "
            f"viewport={self._viewport!r}, "
            f"game_units={self._width:.2f}x{self._height:.2f})"
        )
