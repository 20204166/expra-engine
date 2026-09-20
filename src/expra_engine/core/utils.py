"""Core utilities: timing and handler name derivation.

Adapted from ppb/utils.py (PursuedPyBear, Artistic License 2.0).
Removed LoggingMixin and module-file index; kept only the pure
functions needed by the runtime event system.
"""

from __future__ import annotations

from time import perf_counter

from expra_engine.core.string_utils import camel_to_snake

__all__ = ("camel_to_snake", "get_time")


def get_time() -> float:
    """Return current time via perf_counter.

    All runtime timers use this function so delta-time is consistent.
    """
    return perf_counter()
