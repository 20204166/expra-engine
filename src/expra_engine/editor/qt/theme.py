"""Minimal Qt palette from the shared design tokens (``ui.styles.COLORS``).

The design tokens are a dark theme; Qt Widgets default to the platform's light
palette, which would render token-coloured text (console, selection labels)
unreadably. This applies the Fusion style and a palette derived from the same
tokens -- no stylesheet, no custom widgets.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QPalette


def apply_editor_theme(app: Any, colors: dict[str, str]) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors["background"],
        QPalette.ColorRole.WindowText: colors["ink"],
        QPalette.ColorRole.Base: colors["viewport_bg"],
        QPalette.ColorRole.AlternateBase: colors["panel_bg"],
        QPalette.ColorRole.Text: colors["ink"],
        QPalette.ColorRole.Button: colors["card"],
        QPalette.ColorRole.ButtonText: colors["ink"],
        QPalette.ColorRole.ToolTipBase: colors["card"],
        QPalette.ColorRole.ToolTipText: colors["ink"],
        QPalette.ColorRole.Highlight: colors["accent"],
        QPalette.ColorRole.HighlightedText: colors["accent_ink"],
        QPalette.ColorRole.PlaceholderText: colors["ink_3"],
        QPalette.ColorRole.Link: colors["accent"],
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    app.setPalette(palette)


__all__ = ["apply_editor_theme"]
