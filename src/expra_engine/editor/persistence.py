"""Atomic filesystem persistence helpers.

Adapted from System Analyzer maintenance/persistence.py — simplified to
raise OSError directly rather than accepting an error-factory callable.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

_LOG = logging.getLogger(__name__)


def read_text_or_none(path: Path) -> str | None:
    """Return UTF-8 text from *path*, or ``None`` if missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (UnicodeError, OSError) as error:
        _LOG.warning("Could not read %s: %s", path, error)
        return None


def atomic_write_text(path: Path, payload: str, *, prefix: str = "expra") -> None:
    """Atomically replace *path* with *payload* written as UTF-8.

    Creates parent directories as needed.  Raises ``OSError`` on failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OSError(f"Could not create directory {path.parent}: {error}") from error

    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=prefix,
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except OSError:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name)
    except OSError as error:
        raise OSError(f"Could not write {path}: {error}") from error

    fsync_directory(path)


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of *path*'s parent directory after an atomic commit."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        _LOG.warning("Could not fsync directory %s", path.parent)
    finally:
        with contextlib.suppress(OSError):
            os.close(dir_fd)
