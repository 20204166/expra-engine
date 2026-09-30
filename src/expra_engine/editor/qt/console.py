"""Qt console panel for engine and editor messages."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from expra_engine.ui.styles import COLORS


class ConsolePanel(QWidget):
    """Read-only console panel for engine and editor messages."""

    MAX_LINES = 500

    def __init__(self, parent: Any = None, *, colors: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self._colors = colors or COLORS
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("CONSOLE"))
        header.addStretch(1)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear)
        header.addWidget(clear_button)
        layout.addLayout(header)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self.MAX_LINES)
        layout.addWidget(self._text)

    def log(self, message: str, *, level: str = "info") -> None:
        """Append one message. Called on the main thread."""
        color = {
            "warning": self._colors["warning"],
            "error": self._colors["danger"],
        }.get(level, self._colors["ink"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self._text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(message + "\n", fmt)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def text(self) -> str:
        return self._text.toPlainText()

    def _clear(self) -> None:
        self._text.clear()


__all__ = ["ConsolePanel"]
