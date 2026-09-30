"""Qt presentation adapters for shared action and menu contribution logic."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _is_valid(obj: Any) -> bool:
    try:
        import shiboken6

        return bool(shiboken6.isValid(obj))
    except ImportError:  # pragma: no cover - PySide6 always ships shiboken6
        return True


class QtActionWidget:
    """Expose the semantic action-control contract for a Qt button or action."""

    def __init__(self, target: Any) -> None:
        self._target = target
        self._connection: Any = None

    @property
    def target(self) -> Any:
        return self._target

    def is_valid(self) -> bool:
        return _is_valid(self._target)

    def bind_action(self, callback: Callable[[], object]) -> None:
        signal = self._target.triggered if hasattr(self._target, "triggered") else self._target.clicked
        if self._connection is not None:
            signal.disconnect(self._connection)
        self._connection = signal.connect(lambda *_args: callback())

    def set_enabled(self, enabled: bool) -> None:
        self._target.setEnabled(enabled)


__all__ = ["QtActionWidget"]
