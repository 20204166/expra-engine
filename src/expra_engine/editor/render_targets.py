"""Registry for resolving editor render intents to live presentation targets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _RenderTargetRecord:
    callback: Callable[[Any], None]
    active: bool = True


class RenderTargetRegistry:
    """Resolve editor render targets without owning render scheduling."""

    def __init__(self) -> None:
        self._targets: dict[str, _RenderTargetRecord] = {}

    def register(
        self, target: str, callback: Callable[[Any], None], *, replace: bool = False
    ) -> None:
        if not target:
            raise ValueError("Render target cannot be empty")
        existing = self._targets.get(target)
        if existing is not None and not replace:
            raise ValueError(f"Render target already registered: {target}")
        if existing is not None:
            existing.active = False
        self._targets[target] = _RenderTargetRecord(callback)

    def remove(self, target: str) -> None:
        existing = self._targets.pop(target, None)
        if existing is not None:
            existing.active = False

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(self._targets)

    def callback_for(self, target: str) -> Callable[[Any], None]:
        record = self._targets.get(target)
        if record is None:
            raise KeyError(f"Unknown render target: {target}")

        def apply(intent: Any) -> None:
            if record.active:
                record.callback(intent)

        return apply

    def apply(self, intent: Any) -> None:
        self.callback_for(intent.target)(intent)


__all__ = ["RenderTargetRegistry"]
