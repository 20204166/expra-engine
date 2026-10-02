"""Single Python/Rust bridge for renderer-neutral render math.

This module owns optional native-extension discovery, compact input packing,
native-result validation, and canonical Python fallbacks for visibility masks
and batched Camera2D point projection. Consumers should use these public
operations rather than importing the extension.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from importlib import import_module
from numbers import Real
from typing import Any

from expra_engine.core.camera import Camera2D
from expra_engine.runtime.rendering import RenderContext, RenderItem

__all__ = (
    "native_available",
    "native_projection_available",
    "project_camera_points",
    "python_visible_mask",
    "strict_native_project_camera_points",
    "strict_native_visible_mask",
    "visible_items",
)

_LOGGER = logging.getLogger(__name__)
_ITEM_STRIDE = 21
_SPACE_CODES = {"world": 0.0, "viewport": 1.0}
_KIND_CODES = {
    "point": 0.0,
    "rectangle": 1.0,
    "rect": 2.0,
    "circle": 3.0,
    "rounded_rectangle": 4.0,
    "polygon": 5.0,
    "line": 6.0,
}

_native_module: Any | None
try:
    _native_module = import_module("expra_render_math")
except (ImportError, OSError):  # Optional acceleration; pure Python stays available.
    _native_module = None

_native_disabled = False
_native_failure_reported = False
_native_projection_disabled = False
_native_projection_failure_reported = False
_PROJECTION_CAMERA_STRIDE = 8


def native_available() -> bool:
    """Whether the optional PyO3 module is loaded and enabled for this process."""
    return _native_module is not None and not _native_disabled


def native_projection_available() -> bool:
    """Whether the optional module provides an enabled batch-projection kernel."""
    return (
        native_available()
        and not _native_projection_disabled
        and callable(getattr(_native_module, "project_points", None))
    )


def _pack_visibility_inputs(
    items: tuple[RenderItem, ...], context: RenderContext
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Pack render contracts once per batch; Rust does not inspect Python objects."""
    records: list[float] = []
    points: list[float] = []
    for item in items:
        transform = item.visual_transform
        anchor = item.viewport_anchor or (0.0, 0.0)
        point_start = len(points) // 2
        for point_x, point_y in item.primitive.points:
            points.extend((float(point_x), float(point_y)))
        records.extend(
            (
                _SPACE_CODES[item.space.value],
                _KIND_CODES.get(item.primitive.kind, 7.0),
                1.0 if item.visible else 0.0,
                transform.position[0],
                transform.position[1],
                transform.position[2],
                transform.rotation,
                transform.scale[0],
                transform.scale[1],
                item.primitive.size[0],
                item.primitive.size[1],
                1.0 if item.primitive.radius is not None else 0.0,
                item.primitive.radius or 0.0,
                item.primitive.thickness,
                item.material.outline_width,
                anchor[0],
                anchor[1],
                item.viewport_offset[0],
                item.viewport_offset[1],
                float(point_start),
                float(len(item.primitive.points)),
            )
        )
    camera = context.camera
    camera_values = [
        camera.position[0],
        camera.position[1],
        camera.offset[0],
        camera.offset[1],
        camera.width,
        camera.height,
        camera.rotation,
        camera.near,
        camera.far,
    ]
    viewport = context.viewport
    viewport_values = [
        float(viewport.x),
        float(viewport.y),
        float(viewport.width),
        float(viewport.height),
    ]
    return records, points, camera_values, viewport_values


def python_visible_mask(
    items: Iterable[RenderItem], context: RenderContext
) -> tuple[bool, ...]:
    """The reference implementation: exactly RenderItem.is_visible per item."""
    return tuple(item.is_visible(context) for item in items)


def _invoke_native_visible_mask(
    items: tuple[RenderItem, ...], context: RenderContext
) -> tuple[bool, ...]:
    if _native_module is None:
        raise RuntimeError("native render-math extension is not installed")
    records, points, camera, viewport = _pack_visibility_inputs(items, context)
    mask = _native_module.visible_mask(records, points, camera, viewport)
    if not isinstance(mask, (list, tuple)) or len(mask) != len(items):
        raise ValueError("native visibility mask length does not match the item batch")
    if any(type(value) is not bool for value in mask):
        raise TypeError("native visibility mask must contain only bool values")
    return tuple(mask)


def _finite_real(value: object, name: str) -> float:
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite") from error
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _projection_points(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    try:
        iterator = iter(points)
    except TypeError as error:
        raise TypeError("points must be an iterable of coordinate pairs") from error
    normalized: list[tuple[float, float]] = []
    for index, point in enumerate(iterator):
        if type(point) is tuple:
            coordinates = point
        else:
            if isinstance(point, (str, bytes)) or not isinstance(point, Sequence):
                raise TypeError(f"points[{index}] must be a numeric coordinate pair")
            try:
                coordinates = tuple(point)
            except TypeError as error:
                raise TypeError(f"points[{index}] must be a numeric coordinate pair") from error
        if len(coordinates) != 2:
            raise ValueError(f"points[{index}] must contain exactly two coordinates")
        normalized.append(
            (
                _finite_real(coordinates[0], f"points[{index}].x"),
                _finite_real(coordinates[1], f"points[{index}].y"),
            )
        )
    return tuple(normalized)


def _projection_camera_values(
    camera: Camera2D, viewport: tuple[int | float, int | float]
) -> list[float]:
    if not isinstance(camera, Camera2D):
        raise TypeError("camera must be a Camera2D")
    try:
        dimensions = tuple(viewport)
    except TypeError as error:
        raise TypeError("viewport must contain width and height") from error
    if len(dimensions) != 2:
        raise ValueError("viewport must contain exactly two dimensions")
    width = _finite_real(dimensions[0], "viewport.width")
    height = _finite_real(dimensions[1], "viewport.height")
    if width <= 0.0 or height <= 0.0:
        raise ValueError("viewport dimensions must be positive")

    center_x = _finite_real(camera.position[0] + camera.offset[0], "camera.center_x")
    center_y = _finite_real(camera.position[1] + camera.offset[1], "camera.center_y")
    pixel_ratio = _finite_real(camera.pixel_ratio, "camera.pixel_ratio")
    if pixel_ratio <= 0.0:
        raise ValueError("camera.pixel_ratio must be positive")
    return [
        _finite_real(camera.left, "camera.left"),
        _finite_real(camera.top, "camera.top"),
        pixel_ratio,
        center_x,
        center_y,
        _finite_real(camera.rotation, "camera.rotation"),
        width,
        height,
    ]


def _validate_projected_points(
    result: object, expected_points: int
) -> tuple[tuple[float, float], ...]:
    if not isinstance(result, (list, tuple)) or len(result) != expected_points * 2:
        raise ValueError("native projection result length does not match the point batch")
    values = tuple(_finite_real(value, "native projected coordinate") for value in result)
    return tuple((values[index], values[index + 1]) for index in range(0, len(values), 2))


def _python_project_camera_points(
    points: tuple[tuple[float, float], ...], camera: Camera2D
) -> tuple[tuple[float, float], ...]:
    projected = tuple(camera.translate_to_screen(point) for point in points)
    return tuple(
        (
            _finite_real(point[0], "projected x"),
            _finite_real(point[1], "projected y"),
        )
        for point in projected
    )


def _invoke_native_project_camera_points(
    points: tuple[tuple[float, float], ...], camera_values: list[float]
) -> tuple[tuple[float, float], ...]:
    if _native_module is None:
        raise RuntimeError("native render-math extension is not installed")
    flat_points = [coordinate for point in points for coordinate in point]
    native_project = getattr(_native_module, "project_points", None)
    if not callable(native_project):
        raise RuntimeError("native camera-projection kernel is not installed")
    result = native_project(flat_points, camera_values)
    return _validate_projected_points(result, len(points))


def _disable_native(error: Exception, fallback: str) -> None:
    global _native_disabled, _native_failure_reported
    _native_disabled = True
    if not _native_failure_reported:
        _LOGGER.warning(
            "Native render-math bridge failed; using the %s: %s",
            fallback,
            type(error).__name__,
        )
        _native_failure_reported = True


def strict_native_project_camera_points(
    points: Iterable[tuple[float, float]],
    camera: Camera2D,
    viewport: tuple[int | float, int | float],
) -> tuple[tuple[float, float], ...]:
    """Run the Rust projection kernel without a Python fallback."""
    normalized = _projection_points(points)
    camera_values = _projection_camera_values(camera, viewport)
    if not native_projection_available():
        raise RuntimeError("native render-math extension is not available")
    return _invoke_native_project_camera_points(normalized, camera_values)


def project_camera_points(
    points: Iterable[tuple[float, float]],
    camera: Camera2D,
    viewport: tuple[int | float, int | float],
) -> tuple[tuple[float, float], ...]:
    """Project a batch of world points with the Camera2D reference semantics.

    Inputs and results are validated at the bridge. An unavailable or malformed
    native operation disables acceleration for this process and falls back to
    the canonical per-point ``Camera2D.translate_to_screen`` implementation.
    """
    normalized = _projection_points(points)
    camera_values = _projection_camera_values(camera, viewport)
    if not normalized:
        return ()
    if not native_projection_available():
        return _python_project_camera_points(normalized, camera)
    try:
        return _invoke_native_project_camera_points(normalized, camera_values)
    except Exception as error:  # noqa: BLE001 - optional acceleration fails closed to reference math.
        _disable_native_projection(error)
        return _python_project_camera_points(normalized, camera)


def _disable_native_projection(error: Exception) -> None:
    global _native_projection_disabled, _native_projection_failure_reported
    _native_projection_disabled = True
    if not _native_projection_failure_reported:
        _LOGGER.warning(
            "Native camera-projection kernel failed; using the Python camera-projection reference: %s",
            type(error).__name__,
        )
        _native_projection_failure_reported = True


def strict_native_visible_mask(
    items: Iterable[RenderItem], context: RenderContext
) -> tuple[bool, ...]:
    """Run the Rust kernel with no Python fallback; raise if it cannot run."""
    if not native_available():
        raise RuntimeError("native render-math extension is not available")
    return _invoke_native_visible_mask(tuple(items), context)


def _native_visible_mask(
    items: tuple[RenderItem, ...], context: RenderContext
) -> tuple[bool, ...] | None:
    if _native_module is None or _native_disabled:
        return None
    try:
        return _invoke_native_visible_mask(items, context)
    except Exception as error:  # noqa: BLE001 - optional acceleration must fail over safely.
        _disable_native(error, "Python visibility reference")
        return None


def visible_items(
    ordered_items: Iterable[RenderItem], context: RenderContext
) -> tuple[RenderItem, ...]:
    """Return visible ordered items through one native-or-Python batch boundary."""
    items = tuple(ordered_items)
    mask = _native_visible_mask(items, context)
    if mask is None:
        mask = python_visible_mask(items, context)
    return tuple(item for item, is_visible in zip(items, mask, strict=True) if is_visible)
