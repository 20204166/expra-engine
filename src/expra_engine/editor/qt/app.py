"""Qt editor application entry: preflight, ``QApplication``, editor window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from expra_engine.core.engine import Engine
from expra_engine.editor.qt.main_window import EditorWindow
from expra_engine.editor.qt.preflight import qt_startup_problem
from expra_engine.editor.qt.theme import apply_editor_theme
from expra_engine.ui.styles import accent_theme_colors


def run_qt_editor(engine: Engine, argv: list[str] | None = None) -> int:
    """Build the Qt editor window and run its event loop; return the exit code."""
    problem = qt_startup_problem()
    if problem is not None:
        raise SystemExit(problem)
    _app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    apply_editor_theme(_app, accent_theme_colors("cyan"))
    window = EditorWindow(engine)
    if engine.project is None:
        window.show_project_welcome()
    try:
        return window.run()
    except KeyboardInterrupt:
        window._on_close()
        return 130


__all__ = ["run_qt_editor"]
