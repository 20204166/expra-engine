"""Scene hierarchy panel with retained selection and parent nesting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.scene import Scene
from expra_engine.ui.styles import (
    COLORS,
    EDITOR_ENTITY_MARKERS,
    FONTS,
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_TREEVIEW,
    editor_entity_kind,
)


class HierarchyPanel(tk.Frame):
    """Display a scene's entity hierarchy and expose editor actions."""

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        actions: Any | None = None,
        on_select: Callable[[str | None], None] | None = None,
        on_create: Callable[[], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._actions = actions
        self._on_select = on_select
        self._on_create = on_create
        self._on_delete = on_delete
        self._entity_ids: list[str] = []
        self._selected_id: str | None = None

        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 6))
        tk.Label(
            header,
            text="HIERARCHY",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(side="left")
        add_btn = ttk.Button(header, text="+  Add", style=STYLE_NEUTRAL_BUTTON)
        add_btn.pack(side="right")
        if actions is not None:
            actions.bind(add_btn, "add_entity")
        else:
            add_btn.configure(command=self._handle_create)

        list_frame = tk.Frame(self, bg=c["panel_bg"])
        list_frame.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=(0, 8))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self._tree = ttk.Treeview(
            list_frame,
            show="tree",
            selectmode="browse",
            style=STYLE_TREEVIEW,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=self._tree.yview)
        scrollbar.pack(side="right", fill="y", padx=(SPACING["scrollbar_gutter"], 0))
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.tag_configure("disabled", foreground=c["ink_3"])
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Return>", self._on_tree_activate)

        footer = tk.Frame(self, bg=c["panel_bg"])
        footer.pack(fill="x", padx=SPACING["card_pad_x"], pady=(0, SPACING["card_pad_y"]))
        delete_btn = ttk.Button(footer, text="Delete", style=STYLE_NEUTRAL_BUTTON)
        delete_btn.pack(side="right")
        self._delete_button = delete_btn
        if actions is not None:
            actions.bind(delete_btn, "delete_entity")
        else:
            delete_btn.configure(command=self._handle_delete)

    def render(self, scene: Scene | None) -> None:
        """Refresh entities while retaining stable Treeview rows and state."""
        selected = self._selected_id
        incoming: list[tuple[str, str, str, tuple[str, ...]]] = []
        if scene is not None:
            for entity in scene.roots():
                self._collect_entity(scene, entity.entity_id, "", incoming)

        incoming_ids = {entity_id for entity_id, _parent, _text, _tags in incoming}
        for entity_id in self._entity_ids:
            if entity_id not in incoming_ids and self._tree.exists(entity_id):
                self._tree.delete(entity_id)

        for entity_id, parent, text, tags in incoming:
            if self._tree.exists(entity_id):
                self._tree.item(entity_id, text=text, tags=tags)
                self._tree.move(entity_id, parent, "end")
            else:
                self._tree.insert(parent, "end", iid=entity_id, text=text, tags=tags)
            self._entity_ids = [item_id for item_id in self._entity_ids if item_id != entity_id]
        self._entity_ids.extend(entity_id for entity_id, _parent, _text, _tags in incoming)
        if selected is not None and self._tree.exists(selected):
            self.select(selected)
        else:
            self._selected_id = None

    def _collect_entity(
        self,
        scene: Scene,
        entity_id: str,
        parent: str,
        incoming: list[tuple[str, str, str, tuple[str, ...]]],
    ) -> None:
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        state = "disabled" if not entity.enabled else ""
        kind = editor_entity_kind(entity.name)
        label = (
            f"[{EDITOR_ENTITY_MARKERS[kind]}] {entity.name}" if kind is not None else entity.name
        )
        incoming.append((entity.entity_id, parent, label, (state,) if state else ()))
        for child in scene.children_of(entity.entity_id):
            self._collect_entity(scene, child.entity_id, entity.entity_id, incoming)

    def select(self, entity_id: str | None) -> None:
        self._selected_id = entity_id
        current = self._tree.selection()
        if entity_id is None:
            if current:
                self._tree.selection_remove(current)
            return
        if self._tree.exists(entity_id):
            if current != (entity_id,):
                self._tree.selection_remove(current)
                self._tree.selection_set(entity_id)
            self._tree.focus(entity_id)
            self._tree.see(entity_id)

    def _on_tree_select(self, _event: Any = None) -> None:
        selection = self._tree.selection()
        selected_id = selection[0] if selection else None
        if selected_id == self._selected_id:
            return
        self._selected_id = selected_id
        if self._on_select is not None:
            self._on_select(self._selected_id)

    def _on_tree_activate(self, _event: Any = None) -> str:
        if self._selected_id is not None:
            self._tree.item(self._selected_id, open=True)
        return "break"

    def _handle_create(self) -> None:
        if self._on_create is not None:
            self._on_create()

    def _handle_delete(self) -> None:
        if self._selected_id is not None and self._on_delete is not None:
            self._on_delete(self._selected_id)
