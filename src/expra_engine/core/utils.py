"""Core utilities: timing and handler name derivation.

Adapted from ppb/utils.py (PursuedPyBear, Artistic License 2.0).
Removed LoggingMixin and module-file index; kept only the pure
functions needed by the runtime event system.
"""

from __future__ import annotations

import re
from time import perf_counter

__all__ = ("camel_to_snake", "get_time")

_BOUNDARIES_1 = re.compile(r"(.)([A-Z][a-z]+)")
_BOUNDARIES_2 = re.compile(r"([a-z0-9])([A-Z])")
_handler_name_cache: dict[str, str] = {}


def camel_to_snake(txt: str) -> str:
    """Convert CamelCase class name to snake_case handler name.

    Used to derive event handler names: ``Update`` → ``on_update``.
    Cached for performance.
    """
    result = _handler_name_cache.get(txt)
    if result is None:
        s1 = _BOUNDARIES_1.sub(r"\1_\2", txt)
        result = _BOUNDARIES_2.sub(r"\1_\2", s1).lower()
        _handler_name_cache[txt] = result
    return result


def get_time() -> float:
    """Return current time via perf_counter.

    All runtime timers use this function so delta-time is consistent.
    """
    return perf_counter()
