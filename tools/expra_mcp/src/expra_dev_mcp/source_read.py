"""source_read: bounded, paginated file reads across the six source roots.

Never dumps a whole large file by default -- callers get an explicit
start/end window (or a best-effort ``symbol`` lookup) and a hard line cap,
with ``truncated`` reported when the requested window exceeded it.
"""

from __future__ import annotations

import re

from . import source_access
from .source_access import SourceRoot

DEFAULT_MAX_LINES = 400


def _find_symbol_line(lines: list[str], symbol: str) -> int | None:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    for idx, line in enumerate(lines):
        if pattern.search(line):
            return idx
    return None


def read_source(
    root: SourceRoot,
    relative_path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    symbol: str | None = None,
    context_before: int = 0,
    context_after: int = 0,
    max_lines: int = DEFAULT_MAX_LINES,
) -> tuple[str, int, int, int, bool]:
    """Returns ``(content, actual_start_line, actual_end_line, total_lines, truncated)``.

    ``symbol`` is a best-effort whole-word line search (not a real parser for
    C++/Python/GDScript) -- it locates the first line containing the symbol
    and centers a window around it. For precise extraction, callers should
    pass an explicit ``start_line``/``end_line`` found via source_search.
    """

    resolved = source_access.resolve_relative_path(root, relative_path)
    if not resolved.is_file():
        raise source_access.SourceAccessError(f"not a file: {relative_path!r} in {root.id!r}")
    if source_access.is_probably_binary(resolved):
        raise source_access.SourceAccessError(f"refusing to read binary file: {relative_path!r}")

    text = resolved.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    if start_line is None and end_line is None and symbol:
        found = _find_symbol_line(lines, symbol)
        if found is None:
            raise source_access.SourceAccessError(f"symbol {symbol!r} not found in {relative_path!r}")
        start_line = found + 1
        end_line = found + 1
        context_before = context_before or 5
        context_after = context_after or 40

    if start_line is None and end_line is None:
        lo, hi = 0, min(total_lines, max_lines)
    else:
        lo = max(0, (start_line or 1) - 1 - context_before)
        requested_end = end_line if end_line is not None else (start_line or 1)
        hi = min(total_lines, requested_end + context_after)

    truncated = False
    if hi - lo > max_lines:
        hi = lo + max_lines
        truncated = True

    content = "\n".join(lines[lo:hi])
    return content, lo + 1, hi, total_lines, truncated
