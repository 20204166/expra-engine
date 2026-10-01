"""Single Python/Rust bridge for renderer-neutral visibility calculations.

This module owns optional native-extension discovery, compact input packing,
native-result validation, and the canonical Python fallback. Renderers should
consume ``RenderFrame.visible_items`` rather than importing the extension.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from expra_engine.runtime.rendering import RenderContext, RenderItem

__all__ = (
    "native_available",
    "python_visible_mask",
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

try:
    import expra_render_math as _native_module
except (ImportError, OSError):  # Optional acceleration; pure Python stays available.
    _native_module: Any | None = None

_native_disabled = False
_native_failure_reported = False


def native_available() -> bool:
    """Whether the optional PyO3 module is loaded and enabled for this process."""
    return _native_module is not None and not _native_disabled


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
    global _native_disabled, _native_failure_reported
    if _native_module is None or _native_disabled:
        return None
    try:
        return _invoke_native_visible_mask(items, context)
    except Exception as error:  # noqa: BLE001 - optional acceleration must fail over safely.
        _native_disabled = True
        if not _native_failure_reported:
            _LOGGER.warning(
                "Native render-math bridge failed; using the Python visibility reference: %s",
                type(error).__name__,
            )
            _native_failure_reported = True
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
