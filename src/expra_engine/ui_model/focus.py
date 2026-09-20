"""Deterministic, renderer-neutral focus traversal."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("FocusEntry", "FocusOrder")


@dataclass(frozen=True, slots=True)
class FocusEntry:
    """One item in a declared focus order."""

    key: str
    enabled: bool = True
    skip: bool = False


@dataclass(frozen=True, slots=True)
class FocusOrder:
    """An ordered focus list with an explicit end-of-list policy."""

    entries: tuple[FocusEntry, ...]
    wrap: bool = False

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if len({entry.key for entry in entries}) != len(entries):
            raise ValueError("focus entry keys must be unique")
        if any(not entry.key for entry in entries):
            raise ValueError("focus entry keys must not be empty")
        object.__setattr__(self, "entries", entries)

    def _focusable(self) -> tuple[str, ...]:
        return tuple(entry.key for entry in self.entries if entry.enabled and not entry.skip)

    def _move(self, current: str | None, step: int) -> str | None:
        focusable = self._focusable()
        if not focusable:
            return None
        if current is None:
            return focusable[0] if step > 0 else focusable[-1]
        try:
            index = tuple(entry.key for entry in self.entries).index(current)
        except ValueError:
            index = -1 if step > 0 else len(self.entries)
        while True:
            index += step
            if self.wrap:
                index %= len(self.entries)
            elif not 0 <= index < len(self.entries):
                return None
            entry = self.entries[index]
            if entry.enabled and not entry.skip:
                return entry.key

    def next(self, current: str | None = None) -> str | None:
        """Return the next focusable key, or ``None`` at a non-wrapping end."""

        return self._move(current, 1)

    def previous(self, current: str | None = None) -> str | None:
        """Return the previous focusable key, or ``None`` at a non-wrapping end."""

        return self._move(current, -1)
