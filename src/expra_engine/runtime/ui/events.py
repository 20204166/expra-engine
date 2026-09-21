"""Backend-neutral UI input events."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UIEvent:
    kind: str
    position: tuple[float, float] | None = None
    key: str | None = None
    button: str = "primary"


__all__ = ("UIEvent",)
