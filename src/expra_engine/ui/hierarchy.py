"""Scene Hierarchy panel.

Displays entities in the active scene; notifies selection changes through
a callback. Entity creation/deletion go through the ButtonCoordinator.

UI COORDINATOR OWNS PRESENTATION — the panel never mutates the scene
directly from its event handlers. It raises action events.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.scene import Scene
from expra_engine.ui.styles import COLORS, FONTS, SPACING, STYLE_NEUTRAL_BUTTON


class HierarchyPanel(tk.Frame):
    """Scene Hierarchy panel showing entities in a list.

    ``on_select(entity_id)`` is called when the user clicks an entity.
    ``on_create()`` is called when the Add Entity button is pressed.
    ``on_delete(entity_id)`` is called when Delete is pressed on the selection.
    """

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        on_select: Callable[[str | None], None] | None = None,
        on_create: Callable[[], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])

        self._on_select = on_select
        self._on_create = on_create
        self._on_delete = on_delete
        self._entity_ids: list[str] = []
        self._selected_id: str | None = None
        self._colors = c

        # Header
        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 0))
        tk.Label(
            header,
            text="Scene Hierarchy",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(side="left")
        add_btn = ttk.Button(header, text="+", width=3, style=STYLE_NEUTRAL_BUTTON)
        add_btn.pack(side="right")
        add_btn.configure(command=self._handle_create)

        # Entity list
        list_frame = tk.Frame(self, bg=c["panel_bg"])
        list_frame.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            selectmode="single",
            bg=c["surface"],
            fg=c["ink"],
            selectbackground=c["selection"],
            selectforeground=c["ink"],
            relief="flat",
            borderwidth=0,
            font=FONTS["body"],
        )
        scrollbar.configure(command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.pack(fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # Footer buttons
        footer = tk.Frame(self, bg=c["panel_bg"])
        footer.pack(fill="x", padx=SPACING["card_pad_x"], pady=(0, SPACING["card_pad_y"]))
        del_btn = ttk.Button(footer, text="Delete", style=STYLE_NEUTRAL_BUTTON)
        del_btn.pack(side="right")
        del_btn.configure(command=self._handle_delete)

    def render(self, scene: Scene | None) -> None:
        """Refresh the entity list from ``scene``. Called on the main thread."""
        self._listbox.delete(0, "end")
        self._entity_ids = []
        self._selected_id = None
        if scene is None:
            return
        for entity in scene.entities:
            icon = "○ " if entity.enabled else "● "
            self._listbox.insert("end", f"{icon}{entity.name}")
            self._entity_ids.append(entity.entity_id)

    def select(self, entity_id: str | None) -> None:
        """Programmatically select an entity (e.g. from Inspector edit)."""
        self._selected_id = entity_id
        self._listbox.selection_clear(0, "end")
        if entity_id is not None and entity_id in self._entity_ids:
            idx = self._entity_ids.index(entity_id)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)

    def _on_listbox_select(self, _event: Any) -> None:
        selection = self._listbox.curselection()
        if not selection:
            self._selected_id = None
            if self._on_select:
                self._on_select(None)
            return
        idx = selection[0]
        if idx < len(self._entity_ids):
            self._selected_id = self._entity_ids[idx]
            if self._on_select:
                self._on_select(self._selected_id)

    def _handle_create(self) -> None:
        if self._on_create:
            self._on_create()

    def _handle_delete(self) -> None:
        if self._selected_id and self._on_delete:
            self._on_delete(self._selected_id)
