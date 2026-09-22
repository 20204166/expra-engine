"""Console / log panel for engine and editor messages.

Reuses generic text/status infrastructure. Messages are appended on
the main thread only. Workers deliver through UICoordinator.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from expra_engine.ui.styles import COLORS, FONTS, SPACING, STYLE_NEUTRAL_BUTTON


class ConsolePanel(tk.Frame):
    """Read-only console panel for engine and editor messages."""

    MAX_LINES = 500

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c

        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 6))
        tk.Label(
            header, text="CONSOLE", font=FONTS["panel_header"], bg=c["panel_bg"], fg=c["ink"]
        ).pack(side="left")
        clear_btn = ttk.Button(
            header, text="Clear", style=STYLE_NEUTRAL_BUTTON, command=self._clear
        )
        clear_btn.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=SPACING["card_pad_x"])
        text_frame = tk.Frame(self, bg=c["panel_bg"])
        text_frame.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=6)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        self._text = tk.Text(
            text_frame,
            state="disabled",
            font=FONTS["mono"],
            bg=c["viewport_bg"],
            fg=c["ink"],
            relief="flat",
            borderwidth=0,
            yscrollcommand=scrollbar.set,
            wrap="word",
        )
        scrollbar.configure(command=self._text.yview)
        scrollbar.pack(side="right", fill="y")
        self._text.pack(fill="both", expand=True)

    def log(self, message: str, *, level: str = "info") -> None:
        """Append one message. Called on the main thread."""
        tag_colors = {
            "info": self._text.cget("fg"),
            "warning": self._colors["warning"],
            "error": self._colors["danger"],
        }
        color = tag_colors.get(level, tag_colors["info"])
        self._text.configure(state="normal")

        # Trim if over max
        lines = int(self._text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self._text.delete("1.0", f"{lines - self.MAX_LINES}.0")

        tag = f"level_{level}"
        self._text.tag_configure(tag, foreground=color)
        self._text.insert("end", message + "\n", tag)
        self._text.configure(state="disabled")
        self._text.see("end")

    def _clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
