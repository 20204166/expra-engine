"""Headless atomic filesystem persistence primitives."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any


def atomic_write_text(path: Path, payload: str, *, prefix: str = "expra") -> None:
    """Atomically replace *path* with UTF-8 text and fsync the parent."""
    _atomic_replace(path, prefix, "w", "utf-8", lambda handle: handle.write(payload))


def atomic_write_bytes(path: Path, payload: bytes, *, prefix: str = "expra") -> None:
    """Atomically replace *path* with raw bytes and fsync the parent."""
    _atomic_replace(path, prefix, "wb", None, lambda handle: handle.write(payload))


def _atomic_replace(
    path: Path,
    prefix: str,
    mode: str,
    encoding: str | None,
    write: Callable[[IO[Any]], object],
) -> None:
    """Write *path* via a same-directory temp file, then fsync and rename it in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, mode, encoding=encoding) as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    fsync_directory(path)


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of a file's parent directory."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)
