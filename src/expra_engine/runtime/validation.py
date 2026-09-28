"""Shared low-level validation for renderer-neutral runtime values."""

from __future__ import annotations

import math
from typing import Any, cast

from expra_engine.core.math_utils import finite_float

__all__ = ("coerce_finite_float", "finite_float", "pair_values")


def coerce_finite_float(value: object, name: str) -> float:
    """Coerce an arbitrary value, mapping conversion failures to field validation."""
    try:
        converted = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def pair_values(
    value: object,
    name: str,
    *,
    expectation: str = "two finite numbers",
) -> tuple[Any, Any]:
    """Extract two values while preserving the caller's established diagnostic."""
    message = f"{name} must contain {expectation}"
    if isinstance(value, (str, bytes)):
        raise ValueError(message)
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(message) from exc
    if len(values) != 2:
        raise ValueError(message)
    return cast(tuple[Any, Any], values)
