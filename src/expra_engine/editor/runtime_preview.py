"""Tk scheduling adapter for the editor's embedded runtime preview."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from typing import Any

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
            return
        try:
            self._after_id = self._root.after(16, self._tick)
        except (RuntimeError, tk.TclError):
            if self._root_exists():
                raise
            self._after_id = None

    def stop(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(RuntimeError, tk.TclError):
                self._root.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        if not self._root_exists():
            return
        if self._engine.run_state == EngineRunState.PLAY:
            observer = self._observer
            token = observer.begin("editor:preview:tick") if observer is not None else None
            try:
                self._engine.tick()
                self._render()
            finally:
                if observer is not None and token is not None:
                    observer.finish(token)
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

    def _root_exists(self) -> bool:
        exists = getattr(self._root, "winfo_exists", None)
        if exists is None:
            return True
        try:
            return bool(exists())
        except (RuntimeError, tk.TclError):
            return False


__all__ = ["RuntimePreviewLoop"]
