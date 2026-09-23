"""source_search backends: ripgrep when available, a pure-Python walker
fallback otherwise.

The fallback is not defensive boilerplate here -- `rg` genuinely is not on
this machine's PATH (it exists only inside OpenCode's own cache directory;
workspace_doctor's tools[] list surfaces this), so the pure-Python path is
the one actually exercised in this environment's tests.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import command_runner
from .source_access import (
    DEFAULT_EXCLUDE_DIR_NAMES,
    SourceRoot,
    is_probably_binary,
    iter_source_files,
)

MAX_FILE_READ_BYTES = 2 * 1024 * 1024


@dataclass
class SearchMatch:
    repository: str
    relative_path: str
    line_number: int
    match: str
    context: list[str]
    context_start_line: int


def _compile_pattern(query: str, mode: str) -> re.Pattern[str]:
    return re.compile(re.escape(query)) if mode == "literal" else re.compile(query)


async def search_root(
    root: SourceRoot,
    *,
    query: str,
    mode: str,
    path_globs: list[str] | None,
    exclude_globs: list[str] | None,
    context_lines: int,
    max_results: int,
) -> tuple[list[SearchMatch], bool]:
    """Return ``(matches, truncated)``."""

    if max_results <= 0:
        return [], False

    rg_path = shutil.which("rg")
    if rg_path is not None:
        return await _search_with_ripgrep(
            rg_path,
            root,
            query=query,
            mode=mode,
            path_globs=path_globs,
            exclude_globs=exclude_globs,
            context_lines=context_lines,
            max_results=max_results,
        )
    return await asyncio.to_thread(
        _search_pure_python,
        root,
        query=query,
        mode=mode,
        path_globs=path_globs,
        exclude_globs=exclude_globs,
        context_lines=context_lines,
        max_results=max_results,
    )


async def _search_with_ripgrep(
    rg_path: str,
    root: SourceRoot,
    *,
    query: str,
    mode: str,
    path_globs: list[str] | None,
    exclude_globs: list[str] | None,
    context_lines: int,
    max_results: int,
) -> tuple[list[SearchMatch], bool]:
    argv = [rg_path, "--json", "--context", str(context_lines)]
    argv.append("--fixed-strings" if mode == "literal" else "--pcre2")
    for name in DEFAULT_EXCLUDE_DIR_NAMES:
        argv += ["--glob", f"!**/{name}/**"]
    for pattern in exclude_globs or []:
        argv += ["--glob", f"!{pattern}"]
    for pattern in path_globs or []:
        argv += ["--glob", pattern]
    argv += [query, str(root.path)]

    result = await command_runner.run_command(argv, timeout_seconds=30, max_output_bytes=4 * 1024 * 1024)
    if result.launch_error or result.timed_out:
        return [], False

    matches: list[SearchMatch] = []
    truncated = False
    current_path: Path | None = None
    current_events: list[dict] = []

    def flush_file() -> bool:
        """Returns True if max_results was hit and the caller should stop."""
        nonlocal matches, truncated
        if current_path is None:
            return False
        try:
            rel = current_path.relative_to(root.path).as_posix()
        except ValueError:
            rel = str(current_path)
        for idx, event in enumerate(current_events):
            if event["kind"] != "match":
                continue
            if len(matches) >= max_results:
                truncated = True
                return True
            lo = max(0, idx - context_lines)
            hi = min(len(current_events), idx + context_lines + 1)
            matches.append(
                SearchMatch(
                    repository=root.id,
                    relative_path=rel,
                    line_number=event["line_number"],
                    match=event["text"],
                    context=[current_events[i]["text"] for i in range(lo, hi)],
                    context_start_line=current_events[lo]["line_number"],
                )
            )
        return False

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        etype = event.get("type")
        if etype == "begin":
            current_path = Path(event["data"]["path"]["text"])
            current_events = []
        elif etype in ("match", "context"):
            data = event["data"]
            current_events.append(
                {
                    "kind": "match" if etype == "match" else "context",
                    "line_number": data["line_number"],
                    "text": data["lines"]["text"].rstrip("\n"),
                }
            )
        elif etype == "end":
            if flush_file():
                break
            current_path = None
            current_events = []

    return matches, truncated


def _search_pure_python(
    root: SourceRoot,
    *,
    query: str,
    mode: str,
    path_globs: list[str] | None,
    exclude_globs: list[str] | None,
    context_lines: int,
    max_results: int,
) -> tuple[list[SearchMatch], bool]:
    pattern = _compile_pattern(query, mode)
    matches: list[SearchMatch] = []
    truncated = False

    for file_path in iter_source_files(root, path_globs=path_globs, exclude_globs=exclude_globs):
        if len(matches) >= max_results:
            truncated = True
            break
        try:
            if file_path.stat().st_size > MAX_FILE_READ_BYTES:
                continue
        except OSError:
            continue
        if is_probably_binary(file_path):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        lines = text.splitlines()
        rel = file_path.relative_to(root.path).as_posix()
        for idx, line_text in enumerate(lines):
            if not pattern.search(line_text):
                continue
            if len(matches) >= max_results:
                truncated = True
                break
            lo = max(0, idx - context_lines)
            hi = min(len(lines), idx + context_lines + 1)
            matches.append(
                SearchMatch(
                    repository=root.id,
                    relative_path=rel,
                    line_number=idx + 1,
                    match=line_text,
                    context=lines[lo:hi],
                    context_start_line=lo + 1,
                )
            )

    return matches, truncated
