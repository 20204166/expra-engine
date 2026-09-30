"""Shared low-level validation for renderer-neutral runtime values."""

from __future__ import annotations

import math
from typing import Any, cast

from expra_engine.core.math_utils import finite_float

__all__ = (
    "coerce_finite_float",
    "coerce_integer",
    "coerce_non_negative_float",
    "coerce_positive_float",
    "finite_float",
    "pair_values",
)


def coerce_finite_float(value: object, name: str) -> float:
    """Coerce an arbitrary value, mapping conversion failures to field validation."""
    try:
        converted = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def coerce_positive_float(value: object, name: str) -> float:
    """Coerce a finite float that must be strictly greater than zero."""
    converted = coerce_finite_float(value, name)
    if converted <= 0.0:
        raise ValueError(f"{name} must be positive")
    return converted


def coerce_non_negative_float(value: object, name: str) -> float:
    """Coerce a finite float that may be zero but not negative."""
    converted = coerce_finite_float(value, name)
    if converted < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return converted


def coerce_integer(value: object, name: str) -> int:
    """Coerce an exact integer value, rejecting booleans and fractions."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        converted = int(cast(Any, value))
        if float(cast(Any, value)) != converted:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
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
