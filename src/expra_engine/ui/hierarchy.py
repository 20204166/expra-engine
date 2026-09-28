"""Scene hierarchy panel with retained selection and parent nesting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.core.world import World
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
        on_add_level: Callable[[], None] | None = None,
        on_create_connection: Callable[[], None] | None = None,
        on_open_level: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_reparent: Callable[[tuple[str, ...], str | None], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._actions = actions
        self._on_select = on_select
        self._on_create = on_create
        self._on_add_level = on_add_level
        self._on_create_connection = on_create_connection
        self._on_open_level = on_open_level
        self._on_delete = on_delete
        self._on_reparent = on_reparent
        self._entity_ids: list[str] = []
        self._row_state: dict[str, TreeRow] = {}
        self._selected_ids: tuple[str, ...] = ()
        self._drag_start: tuple[int, int] | None = None
        self._drag_ids: tuple[str, ...] = ()
        self._is_world = False
        self._world_document: World | None = None

        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 6))
        self._header_label = tk.Label(
            header,
            text="HIERARCHY",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        )
        self._header_label.pack(side="left")
        add_btn = ttk.Button(header, text="+  Add", style=STYLE_NEUTRAL_BUTTON)
        self._add_button = add_btn
        add_btn.pack(side="right")
        if actions is not None:
            actions.bind(add_btn, "add_entity")
        else:
            add_btn.configure(command=self._handle_create)
        world_add_btn = ttk.Button(header, text="+  Add Level", style=STYLE_NEUTRAL_BUTTON)
        self._world_add_button = world_add_btn
        if actions is not None:
            actions.bind(world_add_btn, "add_world_level")
        else:
            world_add_btn.configure(command=self._handle_add_world_level)
        world_add_btn.pack_forget()
        connection_btn = ttk.Button(header, text="+  Connect", style=STYLE_NEUTRAL_BUTTON)
        self._world_connection_button = connection_btn
        if actions is not None:
            actions.bind(connection_btn, "create_world_connection")
        else:
            connection_btn.configure(command=self._handle_world_connection)
        connection_btn.pack_forget()

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

    def render(self, scene: Scene | World | None) -> None:
        """Reconcile only changed rows while retaining stable Treeview state."""
        selected = self._selected_ids
        self._is_world = isinstance(scene, World)
        self._header_label.configure(text="WORLD" if self._is_world else "HIERARCHY")
        if self._is_world:
            self._add_button.pack_forget()
            self._world_add_button.pack(side="right")
            self._world_connection_button.pack(side="right", padx=(0, 4))
            self._add_button.configure(state="disabled")
            self._world_add_button.configure(state="normal")
            self._delete_button.configure(state="disabled")
            if self._actions is not None:
                self._actions.set_enabled("add_entity", False)
                self._actions.set_enabled("add_world_level", True)
                self._actions.set_enabled("create_world_connection", True)
                self._actions.set_enabled("delete_entity", False)
                self._actions.set_enabled("duplicate_selection", False)
            if self._world_document is scene:
                self.select_many(tuple(item for item in selected if item in self._row_state))
                return
            self._world_document = scene
            incoming = self._collect_world_rows(scene)
        else:
            self._world_document = None
            self._world_add_button.pack_forget()
            self._world_connection_button.pack_forget()
            self._add_button.pack(side="right")
            self._add_button.configure(state="normal")
            if self._actions is not None:
                self._actions.set_enabled("add_world_level", False)
                self._actions.set_enabled("create_world_connection", False)
            self._delete_button.configure(state="normal")
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

    @staticmethod
    def _collect_world_rows(
        world: World,
    ) -> list[tuple[str, str, str, tuple[str, ...]]]:
        """Project only authored World descriptors and connections into rows."""
        rows = [
            ("world:root", "", world.name, ()),
            ("world:levels", "world:root", "Levels", ()),
        ]
        for descriptor in world.levels:
            suffix = " [Initial]" if descriptor.instance_id == world.initial_level_id else ""
            rows.append(
                (
                    f"level:{descriptor.instance_id}",
                    "world:levels",
                    f"{descriptor.instance_id} — {descriptor.resource_path}{suffix}",
                    (),
                )
            )
        rows.append(("world:connections", "world:root", "Connections", ()))
        level_names = {item.instance_id: item.instance_id for item in world.levels}
        for connection in world.connections:
            label = (
                f"{level_names[connection.source_level_id]}.{connection.source_anchor_id} "
                f"→ {level_names[connection.destination_level_id]}."
                f"{connection.destination_anchor_id} [{connection.transition.value}]"
            )
            rows.append(
                (f"connection:{connection.connection_id}", "world:connections", label, ())
            )
        return rows

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
        current = self._tree.selection()
        valid = tuple(entity_id for entity_id in ids if entity_id in self._row_state)
        if not valid:
            self._selected_ids = ()
            if current:
                self._tree.selection_remove(current)
            return
        if current != valid:
            self._tree.selection_remove(current)
            try:
                self._tree.selection_set(valid)
            except tk.TclError:
                # A row may have disappeared outside reconciliation. Keep the
                # retained-state fast path, but verify against Tk on this error.
                valid = tuple(entity_id for entity_id in valid if self._tree.exists(entity_id))
                if valid:
                    self._tree.selection_set(valid)
        self._selected_ids = valid
        if not valid:
            return
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
            selected = self._selected_ids[0]
            if self._is_world and selected.startswith("level:") and self._on_open_level:
                self._on_open_level(selected.removeprefix("level:"))
            else:
                self._tree.item(selected, open=True)
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
        if start is None or not ids or self._on_reparent is None or self._is_world:
            return
        dx, dy = event.x - start[0], event.y - start[1]
        if dx * dx + dy * dy < _DRAG_THRESHOLD_SQ:
            return  # a plain click/select, not a drag
        target_row = self._tree.identify_row(event.y)
        self._on_reparent(ids, target_row or None)

    def _handle_create(self) -> None:
        if self._on_create is not None:
            self._on_create()

    def _handle_add_world_level(self) -> None:
        if self._on_add_level is not None:
            self._on_add_level()

    def _handle_world_connection(self) -> None:
        if self._on_create_connection is not None:
            self._on_create_connection()

    def _handle_delete(self) -> None:
        if self._selected_ids and self._on_delete is not None:
            self._on_delete(self._selected_ids[0])
