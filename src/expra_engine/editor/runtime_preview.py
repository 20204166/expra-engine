"""Tk scheduling adapter for the editor's embedded runtime preview."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from typing import Any

from expra_engine.core.engine import Engine, EngineRunState


class RuntimePreviewLoop:
    """Drive an Engine from Tk without making the Engine depend on Tk."""

    def __init__(self, root: Any, engine: Engine, render: Callable[[], None]) -> None:
        self._root = root
        self._engine = engine
        self._render = render
        self._after_id: str | None = None

    def start(self) -> None:
        self.stop()
        self._after_id = self._root.after(16, self._tick)

    def stop(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._root.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        if self._engine.run_state == EngineRunState.PLAY:
            self._engine.tick()
            self._render()
        if self._engine.run_state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            self._after_id = self._root.after(16, self._tick)


__all__ = ["RuntimePreviewLoop"]
