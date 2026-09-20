"""Pure caller-driven delayed and repeating invocation helpers."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from expra_engine.runtime.sequence import Func, Sequence, Wait


def _validate_delay(value: float, *, allow_zero: bool = True) -> None:
    if not math.isfinite(value) or value < 0.0 or (not allow_zero and value == 0.0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"delay must be finite and {qualifier}")


def invoke(
    function: Callable[..., Any],
    *args: Any,
    delay: float = 0.0,
    **kwargs: Any,
) -> Sequence | None:
    """Call immediately or return a caller-driven delayed sequence."""
    _validate_delay(delay)
    if delay == 0.0:
        function(*args, **kwargs)
        return None
    return Sequence(Wait(delay), Func(function, args, kwargs))


def after(delay: float) -> Callable[[Callable[..., Any]], Callable[..., Sequence]]:
    """Decorate a function so calls return a delayed :class:`Sequence`."""
    _validate_delay(delay)

    def decorator(function: Callable[..., Any]) -> Callable[..., Sequence]:
        def wrapper(*args: Any, **kwargs: Any) -> Sequence:
            result = invoke(function, *args, delay=delay, **kwargs)
            assert isinstance(result, Sequence)
            return result

        return wrapper

    return decorator


@dataclass
class Repeater:
    function: Callable[..., Any]
    interval: float
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    _elapsed: float = 0.0
    cancelled: bool = False

    def update(self, dt: float) -> int:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if self.cancelled:
            return 0
        self._elapsed += dt
        calls = 0
        while self._elapsed >= self.interval:
            self._elapsed -= self.interval
            self.function(*self.args, **self.kwargs)
            calls += 1
        return calls

    def cancel(self) -> None:
        self.cancelled = True


def every(interval: float) -> Callable[[Callable[..., Any]], Callable[..., Repeater]]:
    """Decorate a function so calls return a caller-driven repeater."""
    _validate_delay(interval, allow_zero=False)

    def decorator(function: Callable[..., Any]) -> Callable[..., Repeater]:
        def wrapper(*args: Any, **kwargs: Any) -> Repeater:
            return Repeater(function, interval, args, kwargs)

        return wrapper

    return decorator


__all__ = ["Repeater", "after", "every", "invoke"]
