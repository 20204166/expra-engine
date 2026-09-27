"""Tk scheduling adapter for the editor's embedded runtime preview."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from typing import Any, Literal

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.observability import ObservabilityWatcher


class RuntimePreviewLoop:
    """Drive an Engine from Tk without making the Engine depend on Tk."""

    def __init__(
        self,
        root: Any,
        engine: Engine,
        render: Callable[[], None],
        *,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        self._root = root
        self._engine = engine
        self._render = render
        self._after_id: str | None = None
        self._observer = observer

    def start(self) -> None:
        self.stop()
        if not self._root_exists():
            self._stop_engine()
            return
        try:
            self._after_id = self._root.after(16, self._tick)
        except (RuntimeError, tk.TclError):
            if self._root_exists():
                raise
            self._after_id = None
            self._stop_engine()

    def stop(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(RuntimeError, tk.TclError):
                self._root.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        if not self._root_exists():
            self._stop_engine()
            return
        if self._engine.run_state == EngineRunState.PLAY:
            observer = self._observer
            token = observer.begin("editor:preview:tick") if observer is not None else None
            outcome: Literal["success", "failure"] = "success"
            try:
                self._engine.tick()
                self._render()
            except Exception:
                outcome = "failure"
                self._stop_engine()
                raise
            finally:
                if observer is not None and token is not None:
                    observer.finish(token, outcome=outcome)
        if (
            self._engine.run_state in (EngineRunState.PLAY, EngineRunState.PAUSED)
            and self._root_exists()
        ):
            try:
                self._after_id = self._root.after(16, self._tick)
            except (RuntimeError, tk.TclError):
                if self._root_exists():
                    raise
                self._after_id = None
                self._stop_engine()

    def _stop_engine(self) -> None:
        """Fail closed: stop the engine when the preview can no longer drive it."""
        observer = self._observer
        try:
            stopped = bool(self._engine.stop())
        except Exception:  # noqa: BLE001 - fail-closed teardown must record, not raise
            if observer is not None:
                observer.record_event("editor:preview:fail_closed", "failure")
            return
        if observer is not None and stopped:
            observer.increment("editor:preview:fail_closed", "stopped")

    def _root_exists(self) -> bool:
        exists = getattr(self._root, "winfo_exists", None)
        if exists is None:
            return True
        try:
            return bool(exists())
        except (RuntimeError, tk.TclError):
            return False


__all__ = ["RuntimePreviewLoop"]
