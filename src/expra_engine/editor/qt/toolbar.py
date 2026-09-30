"""Qt toolbar -- same contribution model and ``action_buttons`` surface as ``ui.toolbar``."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMenu, QPushButton, QToolBar, QToolButton

from expra_engine.editor.contributions import ToolbarContribution
from expra_engine.editor.qt.action_widget import QtActionWidget
from expra_engine.ui.styles import toolbar_style_for_role


def build_toolbar(
    parent: Any,
    *,
    actions: Any,
    contributions: tuple[ToolbarContribution, ...] | None = None,
) -> QToolBar:
    """Build the editor toolbar; every button is bound through ``actions.bind``."""
    toolbar = QToolBar("Main", parent)
    toolbar.setMovable(False)
    if contributions is None:
        contributions = (
            ToolbarContribution("play", "▶  Play", group="runtime", style_role="play"),
            ToolbarContribution("pause", "⏸  Pause", group="runtime"),
            ToolbarContribution("stop", "⏹  Stop", group="runtime", style_role="stop"),
            ToolbarContribution("new_scene", "New Scene", group="scene"),
            ToolbarContribution("save_scene", "Save", group="scene"),
        )
    previous_group: str | None = None
    action_buttons: dict[str, Any] = {}
    for contribution in contributions:
        if previous_group is not None and contribution.group != previous_group:
            toolbar.addSeparator()
        role = toolbar_style_for_role(contribution.style_role)
        button: Any
        if contribution.menu_items:
            button = QToolButton()
            button.setText(contribution.label)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            for item in contribution.menu_items:
                action = menu.addAction(item.label)
                action.triggered.connect(
                    lambda *_a, action_id=item.action_id: actions.dispatch(action_id)
                )
            button.setMenu(menu)
        else:
            button = QPushButton(contribution.label)
        button.setProperty("role", role)
        toolbar.addWidget(button)
        if contribution.action_id is not None:
            actions.bind(QtActionWidget(button), contribution.action_id)
            action_buttons[contribution.action_id] = button
        else:
            action_buttons[contribution.label] = button
        previous_group = contribution.group
    toolbar.action_buttons = action_buttons  # type: ignore[attr-defined]
    return toolbar


__all__ = ["build_toolbar"]
