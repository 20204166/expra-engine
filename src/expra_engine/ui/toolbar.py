"""Editor toolbar — menu bar and Play/Pause/Stop controls.

BUTTON COORDINATOR OWNS ACTIONS. Buttons call coordinator dispatch; no engine
logic lives in this file.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from expra_engine.ui.styles import (
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_PLAY_BUTTON,
    STYLE_STOP_BUTTON,
)


def build_toolbar(
    parent: Any,
    *,
    actions: Any,
    colors: dict[str, str] | None = None,
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

    # --- Play/Pause/Stop ---
    play_btn = ttk.Button(inner, text="▶  Play", style=STYLE_PLAY_BUTTON)
    play_btn.pack(side="left", padx=2)
    actions.bind(play_btn, "play")

    pause_btn = ttk.Button(inner, text="⏸  Pause", style=STYLE_NEUTRAL_BUTTON)
    pause_btn.pack(side="left", padx=2)
    actions.bind(pause_btn, "pause")

    stop_btn = ttk.Button(inner, text="⏹  Stop", style=STYLE_STOP_BUTTON)
    stop_btn.pack(side="left", padx=2)
    actions.bind(stop_btn, "stop")

    sep = ttk.Separator(inner, orient="vertical")
    sep.pack(side="left", fill="y", padx=6, pady=2)

    # --- Project actions ---
    new_scene_btn = ttk.Button(inner, text="New Scene", style=STYLE_NEUTRAL_BUTTON)
    new_scene_btn.pack(side="left", padx=2)
    actions.bind(new_scene_btn, "new_scene")

    save_btn = ttk.Button(inner, text="Save", style=STYLE_NEUTRAL_BUTTON)
    save_btn.pack(side="left", padx=2)
    actions.bind(save_btn, "save_scene")

    return frame
