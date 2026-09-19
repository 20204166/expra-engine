"""Editor application — owns the Tk root and top-level lifecycle."""

from __future__ import annotations

import logging

from expra_engine.core.engine import Engine
from expra_engine.ui.editor_window import EditorWindow

_LOG = logging.getLogger(__name__)


class EditorApplication:
    """Owns the Tk root and drives the editor main loop."""

    def __init__(self, engine: Engine, *, theme: str = "bootstrap-dark") -> None:
        self._engine = engine
        self._theme = theme
        self._window: EditorWindow | None = None

    def run(self) -> None:
        """Build the editor window and start the Tk main loop (blocks until close)."""
        self._window = EditorWindow(self._engine, theme=self._theme)
        self._window.run()
