"""Shared Qt test support: headless (offscreen) QApplication and event pumping."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def qt_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_qt_app():
    """Return the process-wide QApplication, creating it on first use."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    return app


def pump_qt(milliseconds: int = 30) -> None:
    """Process Qt events (timers, queued signals) for ``milliseconds``."""
    app = ensure_qt_app()
    deadline = time.monotonic() + milliseconds / 1000.0
    while True:
        app.processEvents()
        if time.monotonic() >= deadline:
            return
        time.sleep(0.002)
