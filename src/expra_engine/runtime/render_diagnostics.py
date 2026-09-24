"""State-based diagnostics for persistent renderer failures."""

from __future__ import annotations

import logging
from collections.abc import Hashable

FailureKey = tuple[Hashable, ...]

__all__ = ("FailureKey", "RenderDiagnostics")


class RenderDiagnostics:
    """Log each active failure signature once until it resolves."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._active: set[FailureKey] = set()

    def report(self, key: FailureKey, message: str, *args: object) -> None:
        if key not in self._active:
            self._logger.error(message, *args)
        self._active.add(key)

    def resolve(self, key: FailureKey) -> None:
        self._active.discard(key)

    def resolve_prefix(self, prefix: FailureKey) -> None:
        self._active.difference_update(
            {key for key in self._active if key[: len(prefix)] == prefix}
        )

    def clear(self) -> None:
        self._active.clear()

    def active_keys(self) -> tuple[FailureKey, ...]:
        """Return the currently-active failure signatures, most-recent order undefined.

        Read-only introspection for callers (e.g. an MCP tool reporting why a
        pixel render fell back to Canvas) that need to explain *why* rendering
        failed without re-parsing log output.
        """
        return tuple(self._active)
