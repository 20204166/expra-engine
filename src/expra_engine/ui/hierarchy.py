"""Scene hierarchy panel with retained selection and parent nesting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.ui.styles import (
    COLORS,
    EDITOR_ENTITY_MARKERS,
    FONTS,
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_TREEVIEW,
    editor_entity_kind,
)
from expra_engine.ui.tree_reconciliation import TreeRow, reconcile_treeview

_DRAG_THRESHOLD_SQ = 16  # 4px, squared


class HierarchyPanel(tk.Frame):
    """Display a scene's entity hierarchy and expose editor actions."""

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        actions: Any | None = None,
        on_select: Callable[[tuple[str, ...]], None] | None = None,
        on_create: Callable[[], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_reparent: Callable[[tuple[str, ...], str | None], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._actions = actions
        self._on_select = on_select
        self._on_create = on_create
        self._on_delete = on_delete
        self._on_reparent = on_reparent
        self._entity_ids: list[str] = []
        self._row_state: dict[str, TreeRow] = {}
        self._selected_ids: tuple[str, ...] = ()
        self._drag_start: tuple[int, int] | None = None
        self._drag_ids: tuple[str, ...] = ()

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
            selectmode="extended",
            style=STYLE_TREEVIEW,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=self._tree.yview)
        scrollbar.pack(side="right", fill="y", padx=(SPACING["scrollbar_gutter"], 0))
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.tag_configure("disabled", foreground=c["ink_3"])
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Return>", self._on_tree_activate)
        self._tree.bind("<ButtonPress-1>", self._on_press_for_drag, add="+")
        self._tree.bind("<ButtonRelease-1>", self._on_release_for_drag, add="+")

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
        """Reconcile only changed rows while retaining stable Treeview state."""
        selected = self._selected_ids
        incoming = self._collect_entities(scene)
        desired = tuple(
            (entity_id, TreeRow(parent=parent, text=text, tags=tags))
            for entity_id, parent, text, tags in incoming
        )
        self._row_state = reconcile_treeview(self._tree, self._row_state, desired)
        self._entity_ids = [entity_id for entity_id, _parent, _text, _tags in incoming]
        incoming_ids = set(self._row_state)
        kept = tuple(entity_id for entity_id in selected if entity_id in incoming_ids)
        if kept:
            self.select_many(kept)
        else:
            self.select_many(())

    def _collect_entities(self, scene: Scene | None) -> list[tuple[str, str, str, tuple[str, ...]]]:
        """Flatten a scene in stable preorder without recursion depth limits."""
        if scene is None:
            return []
        incoming: list[tuple[str, str, str, tuple[str, ...]]] = []
        stack = [(entity, "") for entity in reversed(scene.roots())]
        while stack:
            entity, parent = stack.pop()
            state = "disabled" if not entity.enabled else ""
            kind = editor_entity_kind(entity.name)
            label = (
                f"[{EDITOR_ENTITY_MARKERS[kind]}] {entity.name}"
                if kind is not None
                else entity.name
            )
            if entity.get_component(SceneInstanceComponent) is not None:
                label = f"[INST] {label}"
            elif scene.is_instance_materialized(entity.entity_id):
                label = f"[in] {label}"
            incoming.append((entity.entity_id, parent, label, (state,) if state else ()))
            children = scene.children_of(entity.entity_id)
            stack.extend((child, entity.entity_id) for child in reversed(children))
        return incoming

    def select(self, entity_id: str | None) -> None:
        """Select a single entity, or clear selection when ``None``."""
        self.select_many((entity_id,) if entity_id is not None else ())

    def select_many(self, entity_ids: tuple[str, ...]) -> None:
        """Select exactly ``entity_ids`` (deduped, order-preserving)."""
        ids = tuple(dict.fromkeys(entity_ids))
        self._selected_ids = ids
        current = self._tree.selection()
        if not ids:
            if current:
                self._tree.selection_remove(current)
            return
        valid = tuple(entity_id for entity_id in ids if self._tree.exists(entity_id))
        if not valid:
            if current:
                self._tree.selection_remove(current)
            return
        if current != valid:
            self._tree.selection_remove(current)
            self._tree.selection_set(valid)
        self._tree.focus(valid[0])
        self._tree.see(valid[0])

    def _on_tree_select(self, _event: Any = None) -> None:
        selection = self._tree.selection()
        if selection == self._selected_ids:
            return
        self._selected_ids = selection
        if self._on_select is not None:
            self._on_select(self._selected_ids)

    def _on_tree_activate(self, _event: Any = None) -> str:
        if self._selected_ids:
            self._tree.item(self._selected_ids[0], open=True)
        return "break"

    def _on_press_for_drag(self, event: Any) -> None:
        self._drag_start = (event.x, event.y)
        row = self._tree.identify_row(event.y)
        if row and row in self._selected_ids:
            self._drag_ids = self._selected_ids
        elif row:
            self._drag_ids = (row,)
        else:
            self._drag_ids = ()

    def _on_release_for_drag(self, event: Any) -> None:
        start = self._drag_start
        ids = self._drag_ids
        self._drag_start = None
        self._drag_ids = ()
        if start is None or not ids or self._on_reparent is None:
            return
        dx, dy = event.x - start[0], event.y - start[1]
        if dx * dx + dy * dy < _DRAG_THRESHOLD_SQ:
            return  # a plain click/select, not a drag
        target_row = self._tree.identify_row(event.y)
        self._on_reparent(ids, target_row or None)

    def _handle_create(self) -> None:
        if self._on_create is not None:
            self._on_create()

    def _handle_delete(self) -> None:
        if self._selected_ids and self._on_delete is not None:
            self._on_delete(self._selected_ids[0])
