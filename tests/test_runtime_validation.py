"""Shared, backend-neutral finite-number conversion contracts."""

from __future__ import annotations

import math

import pytest

from expra_engine.runtime.validation import (
    coerce_finite_float,
    coerce_integer,
    coerce_non_negative_float,
    coerce_positive_float,
    finite_float,
    pair_values,
)


def test_finite_float_preserves_typed_conversion_and_diagnostic_contract() -> None:
    assert finite_float(2, "depth") == 2.0
    with pytest.raises(ValueError, match="depth must be finite"):
        finite_float(math.inf, "depth")


def test_coerce_finite_float_maps_conversion_and_non_finite_failures() -> None:
    assert coerce_finite_float("2.5", "energy") == 2.5
    with pytest.raises(ValueError, match="energy must be finite") as conversion_error:
        coerce_finite_float(object(), "energy")
    assert isinstance(conversion_error.value.__cause__, TypeError)
    with pytest.raises(ValueError, match="energy must be finite") as finite_error:
        coerce_finite_float("nan", "energy")
    assert finite_error.value.__cause__ is None


def test_pair_values_preserves_field_specific_shape_diagnostics() -> None:
    assert pair_values((1, 2), "offset") == (1, 2)
    with pytest.raises(ValueError, match="offset must contain two finite numbers"):
        pair_values("12", "offset")
    with pytest.raises(ValueError, match="origin must contain exactly two finite numbers"):
        pair_values((1, 2, 3), "origin", expectation="exactly two finite numbers")
    with pytest.raises(ValueError, match="offset must contain two finite numbers") as exc_info:
        pair_values(object(), "offset")
    assert isinstance(exc_info.value.__cause__, TypeError)


def test_float_range_coercers_preserve_finite_and_boundary_contracts() -> None:
    assert coerce_positive_float("2.5", "radius") == 2.5
    assert coerce_non_negative_float(0, "damping") == 0.0

    for value in (0, -1, math.inf, math.nan):
        with pytest.raises(ValueError):
            coerce_positive_float(value, "radius")
    for value in (-1, math.inf, math.nan):
        with pytest.raises(ValueError):
            coerce_non_negative_float(value, "damping")


def test_integer_coercer_rejects_booleans_fractions_and_conversion_failures() -> None:
    assert coerce_integer(3.0, "priority") == 3
    for value in (True, 1.5, "not-an-integer", math.inf):
        with pytest.raises(ValueError, match="must be an integer"):
            coerce_integer(value, "priority")
