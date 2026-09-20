"""Atomic filesystem persistence helpers.

Adapted from System Analyzer maintenance/persistence.py — simplified to
raise OSError directly rather than accepting an error-factory callable.
"""

from __future__ import annotations

import logging
from pathlib import Path

from expra_engine.core.persistence import atomic_write_text, fsync_directory

_LOG = logging.getLogger(__name__)

__all__ = ["atomic_write_text", "fsync_directory", "read_text_or_none"]


def read_text_or_none(path: Path) -> str | None:
    """Return UTF-8 text from *path*, or ``None`` if missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (UnicodeError, OSError) as error:
        _LOG.warning("Could not read %s: %s", path, error)
        return None
