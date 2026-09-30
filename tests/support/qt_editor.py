"""Headless Qt editor helpers: build the real editor window and probe its widgets.

``QtEditorHarness`` creates the real ``EditorWindow`` (offscreen Qt) and exposes the few
widget-level probes a test needs (pumping events, reading the console, button labels,
window title, menu labels). Everything else goes through the shared editor logic the
window inherits from ``EditorWindowCore``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from expra_engine.core.engine import Engine
from tests.support.qt_app import ensure_qt_app, pump_qt


class QtEditorHarness:
    def __init__(self, preferences_path: Path | None = None) -> None:
        ensure_qt_app()
        self._preferences_path = preferences_path

    def make(self, engine: Engine | None = None) -> Any:
        from expra_engine.editor.qt.main_window import EditorWindow

        window = EditorWindow(engine or Engine(), preferences_path=self._preferences_path)
        window.show()
        return window

    def pump(self, window: Any = None) -> None:
        pump_qt(20)

    def close(self, window: Any) -> None:
        window._on_close()
        self.pump(window)

    def console_text(self, window: Any) -> str:
        return str(window._console.text())

    def button_text(self, window: Any, action_id: str) -> str:
        return str(window._toolbar.action_buttons[action_id].text())

    def title(self, window: Any) -> str:
        return str(window.windowTitle())

    def file_menu_labels(self, window: Any) -> list[str]:
        return [a.text() for a in window._file_menu.actions() if not a.isSeparator()]

    def recent_labels(self, window: Any) -> list[str]:
        return [a.text() for a in window._recent_menu.actions()]

    def entry_widget_text(self, widget: Any) -> str:
        return str(widget.text())

    def dialogs(self, window: Any) -> Any:
        return window._dialog_provider


def make_editor(engine: Engine | None = None, preferences_path: Path | None = None) -> Any:
    """Build a shown editor window (caller closes it with ``window._on_close()``)."""
    return QtEditorHarness(preferences_path).make(engine)


def pump(window: Any = None, milliseconds: int = 20) -> None:
    """Process Qt events (timers, queued signals) for ``milliseconds``."""
    ensure_qt_app()
    pump_qt(milliseconds)
