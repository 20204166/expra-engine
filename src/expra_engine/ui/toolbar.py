"""Editor toolbar — menu bar and Play/Pause/Stop controls.

BUTTON COORDINATOR OWNS ACTIONS. Buttons call coordinator dispatch; no engine
logic lives in this file.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from expra_engine.editor.contributions import ToolbarContribution
from expra_engine.ui.styles import (
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_PLAY_BUTTON,
    STYLE_STOP_BUTTON,
)

_STYLE_BY_ROLE = {
    "neutral": STYLE_NEUTRAL_BUTTON,
    "play": STYLE_PLAY_BUTTON,
    "stop": STYLE_STOP_BUTTON,
}


def toolbar_style_for_role(style_role: str) -> str:
    """Resolve a semantic toolbar role to an existing ttk style."""
    try:
        return _STYLE_BY_ROLE[style_role]
    except KeyError as error:
        raise ValueError(f"Unknown toolbar style role: {style_role}") from error


def build_toolbar(
    parent: Any,
    *,
    actions: Any,
    colors: dict[str, str] | None = None,
    contributions: tuple[ToolbarContribution, ...] | None = None,
) -> tk.Frame:
    """Build and return the editor toolbar frame.

    ``actions`` is the ButtonCoordinator. All button bindings are made
    through ``actions.bind(widget, action_id)``.
    """
    from expra_engine.ui.styles import COLORS

    c = colors or COLORS
    frame = tk.Frame(parent, bg=c["background"], pady=SPACING["toolbar_pad_y"])
    frame.pack(side="top", fill="x")

    inner = tk.Frame(frame, bg=c["background"])
    inner.pack(side="left", padx=SPACING["toolbar_pad_x"])

    if contributions is None:
        contributions = (
            ToolbarContribution("play", "▶  Play", group="runtime", style_role="play"),
            ToolbarContribution("pause", "⏸  Pause", group="runtime"),
            ToolbarContribution("stop", "⏹  Stop", group="runtime", style_role="stop"),
            ToolbarContribution("new_scene", "New Scene", group="scene"),
            ToolbarContribution("save_scene", "Save", group="scene"),
        )
    previous_group: str | None = None
    for contribution in contributions:
        if previous_group is not None and contribution.group != previous_group:
            sep = ttk.Separator(inner, orient="vertical")
            sep.pack(side="left", fill="y", padx=6, pady=2)
        button = ttk.Button(
            inner,
            text=contribution.label,
            style=toolbar_style_for_role(contribution.style_role),
        )
        button.pack(side="left", padx=2)
        actions.bind(button, contribution.action_id)
        previous_group = contribution.group

    return frame
