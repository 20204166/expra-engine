"""Shared, backend-neutral finite-number conversion contracts."""

from __future__ import annotations

import math

import pytest

from expra_engine.runtime.validation import coerce_finite_float, finite_float, pair_values


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
