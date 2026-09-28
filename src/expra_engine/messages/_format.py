"""Small bounded formatting primitives shared by diagnostic messages."""

from __future__ import annotations


def bounded_text(value: str, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def bounded_repr(value: str | None, limit: int = 120) -> str:
    if value is None:
        return "None"
    text = bounded_text(value, limit)
    return repr(text)
