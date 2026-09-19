"""Inspector panel — shows and edits components for the selected entity.

Changes go through action callbacks; the panel never mutates entity state
directly. BUTTON COORDINATOR / ACTION BOUNDARY OWNS MUTATION.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.ui.styles import COLORS, FONTS, SPACING


class InspectorPanel(tk.Frame):
    """Inspector panel for the selected entity.

    ``on_transform_change(entity_id, field, value)`` is called when a
    transform field is edited.
    ``on_rename(entity_id, new_name)`` is called when the name is changed.
    ``on_toggle_enabled(entity_id, enabled)`` is called for the enabled checkbox.
    """

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        on_transform_change: Callable[[str, str, float], None] | None = None,
        on_rename: Callable[[str, str], None] | None = None,
        on_toggle_enabled: Callable[[str, bool], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])

        self._on_transform_change = on_transform_change
        self._on_rename = on_rename
        self._on_toggle_enabled = on_toggle_enabled
        self._current_entity_id: str | None = None
        self._colors = c

        # Header
        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 0))
        tk.Label(
            header,
            text="Inspector",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(side="left")

        # Scrollable content
        self._content = tk.Frame(self, bg=c["panel_bg"])
        self._content.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=4)

        self._empty_label = tk.Label(
            self._content,
            text="No entity selected",
            font=FONTS["body"],
            bg=c["panel_bg"],
            fg=c["ink_2"],
        )
        self._empty_label.pack(pady=20)

        # Name + enabled row (hidden until entity selected)
        self._name_frame = tk.Frame(self._content, bg=c["panel_bg"])
        self._name_var = tk.StringVar()
        self._enabled_var = tk.BooleanVar(value=True)

        # Transform section
        self._transform_frame = tk.Frame(self._content, bg=c["panel_bg"])
        self._transform_vars: dict[str, tk.StringVar] = {}

    def render(self, entity: Entity | None) -> None:
        """Refresh inspector content for ``entity``."""
        # Clear dynamic content
        for child in tuple(self._content.winfo_children()):
            child.destroy()
        self._name_frame = tk.Frame(self._content, bg=self._colors["panel_bg"])
        self._transform_frame = tk.Frame(self._content, bg=self._colors["panel_bg"])
        self._transform_vars = {}

        if entity is None:
            self._current_entity_id = None
            self._empty_label = tk.Label(
                self._content,
                text="No entity selected",
                font=FONTS["body"],
                bg=self._colors["panel_bg"],
                fg=self._colors["ink_2"],
            )
            self._empty_label.pack(pady=20)
            return

        self._current_entity_id = entity.entity_id
        c = self._colors

        # Name row
        name_row = tk.Frame(self._content, bg=c["panel_bg"])
        name_row.pack(fill="x", pady=(4, 0))
        tk.Label(name_row, text="Name", width=10, anchor="w", bg=c["panel_bg"],
                 fg=c["ink_2"], font=FONTS["detail_row"]).pack(side="left")
        self._name_var = tk.StringVar(value=entity.name)
        name_entry = tk.Entry(name_row, textvariable=self._name_var, font=FONTS["body"],
                              bg=c["surface"], fg=c["ink"], relief="flat", borderwidth=1)
        name_entry.pack(side="left", fill="x", expand=True)
        name_entry.bind("<Return>", self._handle_rename)
        name_entry.bind("<FocusOut>", self._handle_rename)

        # Enabled row
        enabled_row = tk.Frame(self._content, bg=c["panel_bg"])
        enabled_row.pack(fill="x", pady=2)
        tk.Label(enabled_row, text="Enabled", width=10, anchor="w", bg=c["panel_bg"],
                 fg=c["ink_2"], font=FONTS["detail_row"]).pack(side="left")
        self._enabled_var = tk.BooleanVar(value=entity.enabled)
        cb = tk.Checkbutton(
            enabled_row, variable=self._enabled_var, bg=c["panel_bg"],
            command=self._handle_toggle_enabled,
        )
        cb.pack(side="left")

        # Transform component
        transform = entity.get_component(TransformComponent)
        if transform is not None:
            sep = ttk.Separator(self._content, orient="horizontal")
            sep.pack(fill="x", pady=6)
            tk.Label(self._content, text="Transform", font=FONTS["section"],
                     bg=c["panel_bg"], fg=c["ink"]).pack(anchor="w")
            for field_name, label in [
                ("x", "X"), ("y", "Y"),
                ("rotation", "Rotation"),
                ("scale_x", "Scale X"), ("scale_y", "Scale Y"),
            ]:
                row = tk.Frame(self._content, bg=c["panel_bg"])
                row.pack(fill="x", pady=1)
                tk.Label(row, text=label, width=10, anchor="w", bg=c["panel_bg"],
                         fg=c["ink_2"], font=FONTS["detail_row"]).pack(side="left")
                var = tk.StringVar(value=str(getattr(transform, field_name)))
                entry = tk.Entry(row, textvariable=var, font=FONTS["body"], width=10,
                                 bg=c["surface"], fg=c["ink"], relief="flat", borderwidth=1)
                entry.pack(side="left")
                self._transform_vars[field_name] = var
                entry.bind("<Return>", lambda _e, fn=field_name: self._handle_transform(fn))  # type: ignore[misc]
                entry.bind("<FocusOut>", lambda _e, fn=field_name: self._handle_transform(fn))  # type: ignore[misc]

    def _handle_rename(self, _event: Any = None) -> None:
        if self._current_entity_id and self._on_rename:
            self._on_rename(self._current_entity_id, self._name_var.get())

    def _handle_toggle_enabled(self) -> None:
        if self._current_entity_id and self._on_toggle_enabled:
            self._on_toggle_enabled(self._current_entity_id, self._enabled_var.get())

    def _handle_transform(self, field_name: str) -> None:
        if self._current_entity_id is None or self._on_transform_change is None:
            return
        var = self._transform_vars.get(field_name)
        if var is None:
            return
        try:
            value = float(var.get())
        except ValueError:
            return
        self._on_transform_change(self._current_entity_id, field_name, value)
