"""Scene hierarchy panel with retained selection and parent nesting."""

from __future__ import annotations

import tkinter as tk
from bisect import bisect_left
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
        self._row_state: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        self._child_order: dict[str, tuple[str, ...]] = {}
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
        incoming_ids = {entity_id for entity_id, _parent, _text, _tags in incoming}
        stale_ids = set(self._row_state) - incoming_ids

        # Deleting a Treeview parent removes its full subtree. Delete only the
        # stale subtree roots; descendants disappear with their parent.
        for entity_id in self._entity_ids:
            previous = self._row_state.get(entity_id)
            if (
                entity_id in stale_ids
                and previous is not None
                and previous[0] not in stale_ids
                and self._tree.exists(entity_id)
            ):
                self._tree.delete(entity_id)

        desired_children: dict[str, list[str]] = {}
        row_by_id: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        for entity_id, parent, text, tags in incoming:
            desired_children.setdefault(parent, []).append(entity_id)
            row_by_id[entity_id] = (parent, text, tags)
        desired_order = {
            parent: tuple(entity_ids) for parent, entity_ids in desired_children.items()
        }
        desired_indices = {
            entity_id: index
            for entity_ids in desired_order.values()
            for index, entity_id in enumerate(entity_ids)
        }
        working_orders = {
            parent: [
                entity_id
                for entity_id in old_order
                if entity_id in row_by_id and row_by_id[entity_id][0] == parent
            ]
            for parent, old_order in self._child_order.items()
        }

        # Existing siblings only require reordering when their relative order
        # actually changed. Adds/removes/reparents are positioned directly at
        # their requested sibling index below.
        reordered_parents: set[str] = set()
        for parent, entity_ids in desired_order.items():
            old_common = tuple(
                entity_id
                for entity_id in self._child_order.get(parent, ())
                if entity_id in incoming_ids and row_by_id[entity_id][0] == parent
            )
            new_common = tuple(
                entity_id
                for entity_id in entity_ids
                if self._row_state.get(entity_id, (None, "", ()))[0] == parent
            )
            if old_common != new_common:
                reordered_parents.add(parent)

        for entity_id, parent, text, tags in incoming:
            previous = self._row_state.get(entity_id)
            tree_item_exists = previous is not None and self._tree.exists(entity_id)
            index = desired_indices[entity_id]
            if not tree_item_exists:
                siblings = working_orders.setdefault(parent, [])
                insertion_index = min(index, len(siblings))
                if insertion_index == len(siblings):
                    self._tree.insert(parent, "end", iid=entity_id, text=text, tags=tags)
                else:
                    self._tree.insert(parent, insertion_index, iid=entity_id, text=text, tags=tags)
                siblings.insert(insertion_index, entity_id)
            elif previous is not None and previous[0] != parent:
                siblings = working_orders.setdefault(parent, [])
                insertion_index = min(index, len(siblings))
                if insertion_index == len(siblings):
                    self._tree.move(entity_id, parent, "end")
                else:
                    self._tree.move(entity_id, parent, insertion_index)
                siblings.insert(insertion_index, entity_id)
            elif previous is not None and parent not in reordered_parents:
                # Unchanged row order is owned by this panel's cached snapshot;
                # avoid a Tk round trip for a no-op move.
                pass

            if previous is not None and tree_item_exists and previous[1:] != (text, tags):
                self._tree.item(entity_id, text=text, tags=tags)

        for parent in reordered_parents:
            current_order = self._tree.get_children(parent)
            current_positions = {entity_id: index for index, entity_id in enumerate(current_order)}
            desired = desired_order[parent]
            stable_ids = self._longest_stable_siblings(desired, current_positions)
            for index, entity_id in enumerate(desired):
                if entity_id not in stable_ids:
                    self._tree.move(entity_id, parent, index)
            working_orders[parent] = list(desired_order[parent])

        self._row_state = row_by_id
        self._child_order = desired_order
        self._entity_ids = [entity_id for entity_id, _parent, _text, _tags in incoming]
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

    @staticmethod
    def _longest_stable_siblings(
        desired: tuple[str, ...], current_positions: dict[str, int]
    ) -> set[str]:
        """Return a longest in-order subset that can remain unmoved."""
        sequence = [
            (entity_id, current_positions[entity_id])
            for entity_id in desired
            if entity_id in current_positions
        ]
        if not sequence:
            return set()

        tails: list[int] = []
        tail_indices: list[int] = []
        previous = [-1] * len(sequence)
        for index, (_entity_id, position) in enumerate(sequence):
            slot = bisect_left(tails, position)
            if slot:
                previous[index] = tail_indices[slot - 1]
            if slot == len(tails):
                tails.append(position)
                tail_indices.append(index)
            else:
                tails[slot] = position
                tail_indices[slot] = index

        stable: set[str] = set()
        index = tail_indices[-1]
        while index >= 0:
            stable.add(sequence[index][0])
            index = previous[index]
        return stable

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
