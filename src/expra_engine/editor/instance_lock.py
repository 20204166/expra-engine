"""Cross-platform OS-held single-instance lock.

The lock is scoped to the given path so multiple profiles may run
simultaneously.  The OS releases the lock automatically when the process
terminates, including crashes and force-kills, so no stale-lock recovery
is needed.

Adapted from System Analyzer maintenance/instance_lock.py.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path


class InstanceLock:
    """OS-held exclusive lock on a file path.

    Keep this object alive for the duration of the runtime.  The lock is
    released when ``release()`` is called or the process terminates.
    """

    def __init__(self, _file: object) -> None:
        self._file = _file

    def release(self) -> None:
        """Release the lock; safe to call more than once."""
        f = self._file
        if f is not None:
            self._file = None
            with contextlib.suppress(OSError):
                f.close()  # type: ignore[attr-defined]


def acquire(lock_path: Path) -> InstanceLock | None:
    """Try to acquire an exclusive OS-held lock on *lock_path*.

    Returns an ``InstanceLock`` that MUST be kept alive for the lock
    duration.  Returns ``None`` if another process already holds the lock,
    or if the lock file cannot be created.
    """
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(lock_path, "ab")  # noqa: SIM115 — must stay open past this scope
    except OSError:
        return None

    try:
        if sys.platform == "win32":
            import msvcrt  # type: ignore[import]

            lock_file.write(b"\x00")
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None

    return InstanceLock(lock_file)
