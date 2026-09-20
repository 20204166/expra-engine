"""Pure easing functions based on the canonical easings.net formulas."""

from __future__ import annotations

import math
from collections.abc import Callable

EasingFn = Callable[[float], float]


def _validate_t(t: float) -> None:
    if not math.isfinite(t):
        raise ValueError("t must be finite")


def linear(t: float) -> float:
    _validate_t(t)
    return t


def in_sine(t: float) -> float:
    _validate_t(t)
    return 1.0 - math.cos(t * math.pi / 2.0)


def out_sine(t: float) -> float:
    _validate_t(t)
    return math.sin(t * math.pi / 2.0)


def in_out_sine(t: float) -> float:
    _validate_t(t)
    return -(math.cos(math.pi * t) - 1.0) / 2.0


def in_quad(t: float) -> float:
    _validate_t(t)
    return t * t


def out_quad(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 2


def in_out_quad(t: float) -> float:
    _validate_t(t)
    return 2.0 * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0


def in_cubic(t: float) -> float:
    _validate_t(t)
    return t**3


def out_cubic(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 3


def in_out_cubic(t: float) -> float:
    _validate_t(t)
    return 4.0 * t**3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def in_quart(t: float) -> float:
    _validate_t(t)
    return t**4


def out_quart(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 4


def in_out_quart(t: float) -> float:
    _validate_t(t)
    return 8.0 * t**4 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 4 / 2.0


def in_quint(t: float) -> float:
    _validate_t(t)
    return t**5


def out_quint(t: float) -> float:
    _validate_t(t)
    return 1.0 - (1.0 - t) ** 5


def in_out_quint(t: float) -> float:
    _validate_t(t)
    return 16.0 * t**5 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 5 / 2.0


def in_expo(t: float) -> float:
    _validate_t(t)
    return 0.0 if t == 0.0 else 2.0 ** (10.0 * t - 10.0)


def out_expo(t: float) -> float:
    _validate_t(t)
    return 1.0 if t == 1.0 else 1.0 - 2.0 ** (-10.0 * t)


def in_out_expo(t: float) -> float:
    _validate_t(t)
    if t == 0.0 or t == 1.0:
        return t
    return 2.0 ** (20.0 * t - 10.0) / 2.0 if t < 0.5 else (2.0 - 2.0 ** (-20.0 * t + 10.0)) / 2.0


def in_circ(t: float) -> float:
    _validate_t(t)
    return 1.0 - math.sqrt(1.0 - t**2)


def out_circ(t: float) -> float:
    _validate_t(t)
    return math.sqrt(1.0 - (t - 1.0) ** 2)


def in_out_circ(t: float) -> float:
    _validate_t(t)
    return (
        (1.0 - math.sqrt(1.0 - (2.0 * t) ** 2)) / 2.0
        if t < 0.5
        else (math.sqrt(1.0 - (-2.0 * t + 2.0) ** 2) + 1.0) / 2.0
    )


_BACK_C1 = 1.70158
_BACK_C3 = _BACK_C1 + 1.0
_BACK_C2 = _BACK_C1 * 1.525


def in_back(t: float) -> float:
    _validate_t(t)
    return _BACK_C3 * t**3 - _BACK_C1 * t**2


def out_back(t: float) -> float:
    _validate_t(t)
    return 1.0 + _BACK_C3 * (t - 1.0) ** 3 + _BACK_C1 * (t - 1.0) ** 2


def in_out_back(t: float) -> float:
    _validate_t(t)
    return (
        ((2.0 * t) ** 2 * ((_BACK_C2 + 1.0) * 2.0 * t - _BACK_C2)) / 2.0
        if t < 0.5
        else ((2.0 * t - 2.0) ** 2 * ((_BACK_C2 + 1.0) * (t * 2.0 - 2.0) + _BACK_C2) + 2.0) / 2.0
    )


def in_elastic(t: float) -> float:
    _validate_t(t)
    if t == 0.0 or t == 1.0:
        return t
    return -(2.0 ** (10.0 * t - 10.0)) * math.sin((t * 10.0 - 10.75) * (2.0 * math.pi / 3.0))


def out_elastic(t: float) -> float:
    _validate_t(t)
    if t == 0.0 or t == 1.0:
        return t
    return 2.0 ** (-10.0 * t) * math.sin((t * 10.0 - 0.75) * (2.0 * math.pi / 3.0)) + 1.0


def in_out_elastic(t: float) -> float:
    _validate_t(t)
    if t == 0.0 or t == 1.0:
        return t
    if t < 0.5:
        return (
            -(2.0 ** (20.0 * t - 10.0) * math.sin((20.0 * t - 11.125) * (2.0 * math.pi / 4.5)))
            / 2.0
        )
    return (
        2.0 ** (-20.0 * t + 10.0) * math.sin((20.0 * t - 11.125) * (2.0 * math.pi / 4.5))
    ) / 2.0 + 1.0


def out_bounce(t: float) -> float:
    _validate_t(t)
    n1, d1 = 7.5625, 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def in_bounce(t: float) -> float:
    _validate_t(t)
    return 1.0 - out_bounce(1.0 - t)


def in_out_bounce(t: float) -> float:
    _validate_t(t)
    return (
        (1.0 - out_bounce(1.0 - 2.0 * t)) / 2.0
        if t < 0.5
        else (1.0 + out_bounce(2.0 * t - 1.0)) / 2.0
    )


def reverse(fn: EasingFn) -> EasingFn:
    """Return an easing that evaluates *fn* from the opposite direction."""

    def _reversed(t: float) -> float:
        return fn(1.0 - t)

    return _reversed


def combine(fn_a: EasingFn, fn_b: EasingFn, split: float = 0.5) -> EasingFn:
    """Use *fn_a* before *split* and *fn_b* after it."""
    if not 0.0 < split < 1.0:
        raise ValueError("split must be strictly between 0 and 1")

    def _combined(t: float) -> float:
        _validate_t(t)
        if t < split:
            return fn_a(t / split) * split
        return split + fn_b((t - split) / (1.0 - split)) * (1.0 - split)

    return _combined


class CubicBezier:
    """A CSS-style cubic Bezier easing with endpoints (0, 0) and (1, 1)."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        values = (x1, y1, x2, y2)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Bezier control points must be finite")
        if not 0.0 <= x1 <= 1.0 or not 0.0 <= x2 <= 1.0:
            raise ValueError("Bezier x control points must be in [0, 1]")
        self.x1, self.y1, self.x2, self.y2 = values

    def __call__(self, t: float) -> float:
        _validate_t(t)
        if t <= 0.0 or t >= 1.0:
            return t
        parameter = t
        for _ in range(8):
            x = self._x(parameter) - t
            derivative = self._x_derivative(parameter)
            if abs(x) < 1e-9 or derivative == 0.0:
                break
            parameter -= x / derivative
            if parameter < 0.0 or parameter > 1.0:
                parameter = t
                break
        low, high = 0.0, 1.0
        for _ in range(24):
            x = self._x(parameter)
            if abs(x - t) < 1e-9:
                break
            if x < t:
                low = parameter
            else:
                high = parameter
            parameter = (low + high) / 2.0
        return self._y(parameter)

    def _x(self, t: float) -> float:
        return 3.0 * (1.0 - t) ** 2 * t * self.x1 + 3.0 * (1.0 - t) * t**2 * self.x2 + t**3

    def _y(self, t: float) -> float:
        return 3.0 * (1.0 - t) ** 2 * t * self.y1 + 3.0 * (1.0 - t) * t**2 * self.y2 + t**3

    def _x_derivative(self, t: float) -> float:
        return (
            3.0 * (1.0 - t) ** 2 * self.x1
            + 6.0 * (1.0 - t) * t * (self.x2 - self.x1)
            + 3.0 * t**2 * (1.0 - self.x2)
        )


__all__ = [name for name in globals() if not name.startswith("_")]
