"""``get``/``set`` views over Qt input widgets.

The shared inspector and export-dialog logic read and write field values through
small variable-shaped objects (``get()``/``set()``). These wrap a QLineEdit /
QComboBox / QCheckBox so that logic runs unchanged on Qt widgets.
"""

from __future__ import annotations

from typing import Any


class StringVar:
    """``get``/``set`` view of a QLineEdit."""

    def __init__(self, widget: Any) -> None:
        self._widget = widget

    def get(self) -> str:
        return str(self._widget.text())

    def set(self, value: str) -> None:
        self._widget.setText(value)


class ComboVar:
    """``get``/``set`` view of a QComboBox's current text."""

    def __init__(self, widget: Any) -> None:
        self._widget = widget

    def get(self) -> str:
        return str(self._widget.currentText())

    def set(self, value: str) -> None:
        self._widget.setCurrentText(value)


class BooleanVar:
    """``get``/``set`` view of a QCheckBox."""

    def __init__(self, widget: Any) -> None:
        self._widget = widget

    def get(self) -> bool:
        return bool(self._widget.isChecked())

    def set(self, value: bool) -> None:
        self._widget.setChecked(bool(value))


__all__ = ["BooleanVar", "ComboVar", "StringVar"]
