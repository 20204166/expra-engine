"""Headless atomic filesystem persistence primitives."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, payload: str, *, prefix: str = "expra") -> None:
    """Atomically replace *path* with UTF-8 text and fsync the parent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
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
