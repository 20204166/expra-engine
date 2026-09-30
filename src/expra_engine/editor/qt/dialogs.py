"""Qt implementation of the DialogProvider protocol.

QtDialogProvider wraps PySide6's QMessageBox, QFileDialog, and QInputDialog.
All imports are lazy (inside methods) so this module can be imported without
a running QApplication — tests and headless contexts import it safely.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _filetypes_to_qt_filter(filetypes: Sequence[tuple[str, str]]) -> str:
    """Convert ``[(label, pattern), ...]`` filetypes to a Qt filter string."""
    if not filetypes:
        return ""
    parts = [f"{name} ({pattern})" for name, pattern in filetypes]
    return ";;".join(parts)


class QtDialogProvider:
    """DialogProvider implementation backed by PySide6 Qt dialogs."""

    def __init__(self, parent: Any = None) -> None:
        self._parent = parent

    def _p(self, parent: Any) -> Any:
        """Return the effective parent: call-site override first, stored fallback second."""
        return parent if parent is not None else self._parent

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def ask_open_file(
        self,
        title: str,
        *,
        filetypes: Sequence[tuple[str, str]] = (),
        multiple: bool = False,
        initialdir: str = "",
        parent: Any = None,
    ) -> str | list[str]:
        from PySide6.QtWidgets import QFileDialog

        p = self._p(parent)
        filter_str = _filetypes_to_qt_filter(filetypes)
        if multiple:
            paths, _ = QFileDialog.getOpenFileNames(p, title, initialdir or "", filter_str)
            return list(paths) if paths else []
        path, _ = QFileDialog.getOpenFileName(p, title, initialdir or "", filter_str)
        return path or ""

    def ask_open_dir(self, title: str, *, initialdir: str = "", parent: Any = None) -> str:
        from PySide6.QtWidgets import QFileDialog

        p = self._p(parent)
        path = QFileDialog.getExistingDirectory(p, title, initialdir or "")
        return path or ""

    def ask_save_file(
        self,
        title: str,
        *,
        filetypes: Sequence[tuple[str, str]] = (),
        defaultextension: str = "",
        initialfile: str = "",
        initialdir: str = "",
        parent: Any = None,
    ) -> str:
        from PySide6.QtWidgets import QFileDialog

        p = self._p(parent)
        filter_str = _filetypes_to_qt_filter(filetypes)
        start = str(Path(initialdir) / initialfile) if initialdir and initialfile else (
            initialfile or initialdir or ""
        )
        path, _ = QFileDialog.getSaveFileName(p, title, start, filter_str)
        if not path:
            return ""
        if defaultextension and not Path(path).suffix:
            path = path + defaultextension
        return path

    # ------------------------------------------------------------------
    # Input dialog
    # ------------------------------------------------------------------

    def ask_string(
        self,
        title: str,
        prompt: str,
        *,
        initial_value: str = "",
        parent: Any = None,
    ) -> str | None:
        from PySide6.QtWidgets import QInputDialog

        p = self._p(parent)
        text, ok = QInputDialog.getText(p, title, prompt, text=initial_value or "")
        return text if ok else None

    # ------------------------------------------------------------------
    # Message dialogs
    # ------------------------------------------------------------------

    def show_error(self, title: str, message: str, *, parent: Any = None) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(self._p(parent), title, message)

    def show_warning(self, title: str, message: str, *, parent: Any = None) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self._p(parent), title, message)

    def show_info(self, title: str, message: str, *, parent: Any = None) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(self._p(parent), title, message)

    def ask_yes_no(self, title: str, message: str, *, parent: Any = None) -> bool:
        from PySide6.QtWidgets import QMessageBox

        result = QMessageBox.question(self._p(parent), title, message)
        return result == QMessageBox.StandardButton.Yes

    def ask_yes_no_cancel(
        self, title: str, message: str, *, parent: Any = None
    ) -> bool | None:
        from PySide6.QtWidgets import QMessageBox

        buttons = (
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel
        )
        result = QMessageBox.question(self._p(parent), title, message, buttons)
        if result == QMessageBox.StandardButton.Yes:
            return True
        if result == QMessageBox.StandardButton.No:
            return False
        return None


__all__ = ["QtDialogProvider"]
