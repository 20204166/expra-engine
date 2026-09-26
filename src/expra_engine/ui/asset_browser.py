"""Tk asset browser backed by logical project resource IDs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from pathlib import Path
from tkinter import ttk
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.editor.assets import (
    AssetEntry,
    AssetScanRequest,
    AssetScanResult,
    accept_scan_result,
    scan_directory,
)
from expra_engine.observability import ObservabilityWatcher, observe_stage
from expra_engine.ui.styles import (
    COLORS,
    FONTS,
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_TREEVIEW,
)

_DRAG_THRESHOLD_SQ = 16  # 4px, squared -- avoids a sqrt on every motion event


class AssetBrowserPanel(tk.Frame):
    """Browse project assets while exposing logical IDs to editor actions."""

    def __init__(
        self,
        parent: Any,
        *,
        root_directory: Path,
        resource_root: Path | None = None,
        coordinator: AppCoordinator | None = None,
        observer: ObservabilityWatcher | None = None,
        colors: dict[str, str] | None = None,
        on_open: Callable[[AssetEntry], None] | None = None,
        on_drop: Callable[[AssetEntry, int, int], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._coordinator = coordinator
        self._observer = observer
        self._on_open = on_open
        self._on_drop = on_drop
        self._root_directory = Path(root_directory).resolve()
        self._resource_root = Path(resource_root or root_directory).resolve()
        self._current_directory = self._root_directory
        self._generation = 0
        self._selected_entry: AssetEntry | None = None
        self._entries: dict[str, AssetEntry] = {}
        self._entry_parents: dict[str, str] = {}
        self._entry_rows: dict[str, tuple[str, tuple[str, str]]] = {}
        self._entry_sort_keys: dict[str, tuple[int, str, bool]] = {}
        self._child_order: dict[str, tuple[str, ...]] = {}
        self._path_iids: dict[Path, str] = {self._current_directory: "asset-root"}
        self._last_render_key: tuple[Path, Path] | None = None
        self._last_input_entries: tuple[AssetEntry, ...] | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_entry: AssetEntry | None = None

        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 4))
        tk.Label(
            header,
            text="ASSETS",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(side="left")
        ttk.Button(header, text="Up", style=STYLE_NEUTRAL_BUTTON, command=self.navigate_up).pack(
            side="right", padx=(4, 0)
        )
        ttk.Button(header, text="Refresh", style=STYLE_NEUTRAL_BUTTON, command=self.refresh).pack(
            side="right"
        )

        self._path_var = tk.StringVar()
        tk.Label(
            self,
            textvariable=self._path_var,
            anchor="w",
            bg=c["panel_bg"],
            fg=c["ink_2"],
            font=FONTS["detail_row"],
        ).pack(fill="x", padx=SPACING["card_pad_x"], pady=(0, 4))

        list_frame = tk.Frame(self, bg=c["panel_bg"])
        list_frame.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=(0, 8))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self._tree = ttk.Treeview(
            list_frame,
            columns=("kind", "logical_id"),
            displaycolumns=("kind",),
            show="tree headings",
            selectmode="browse",
            style=STYLE_TREEVIEW,
            yscrollcommand=scrollbar.set,
        )
        self._tree.heading("#0", text="Name", anchor="w")
        self._tree.heading("kind", text="Type", anchor="w")
        self._tree.column("kind", width=58, stretch=False)
        self._tree.column("logical_id", width=0, stretch=False)
        scrollbar.configure(command=self._tree.yview)
        scrollbar.pack(side="right", fill="y", padx=(SPACING["scrollbar_gutter"], 0))
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_activate)
        self._tree.bind("<Return>", self._on_activate)
        self._tree.bind("<ButtonPress-1>", self._on_press_for_drag, add="+")
        self._tree.bind("<ButtonRelease-1>", self._on_release_for_drag, add="+")
        self._path_var.set(str(self._current_directory))

    @property
    def root_directory(self) -> Path:
        return self._root_directory

    @property
    def current_directory(self) -> Path:
        return self._current_directory

    def set_root_directory(self, directory: Path) -> None:
        """Switch the browser to a new project asset root."""
        new_root = directory.resolve()
        if new_root != self._root_directory or self._current_directory != new_root:
            self._path_iids = {new_root: "asset-root"}
        self._root_directory = new_root
        self._resource_root = self._root_directory
        self._current_directory = self._root_directory
        self._selected_entry = None
        selection = self._tree.selection()
        if selection:
            self._tree.selection_remove(selection)
        self._path_var.set(str(self._current_directory))
        self.refresh()

    @property
    def selected_entry(self) -> AssetEntry | None:
        return self._selected_entry

    def refresh(self) -> None:
        self._generation += 1
        request = AssetScanRequest(
            directory=self._current_directory,
            generation=self._generation,
            resource_root=self._resource_root,
        )
        if self._coordinator is None:
            self._accept_scan(scan_directory(request, _iter_directory))
            return
        self._coordinator.run(
            f"asset-browser:{id(self)}",
            lambda cancel, _progress: scan_directory(
                request, lambda directory: () if cancel.is_set() else _iter_directory(directory)
            ),
            on_result=lambda _key, result: self._accept_scan(result),
        )

    def render_entries(self, entries: Iterable[AssetEntry]) -> None:
        with observe_stage(self._observer, "ui:assets:populate"):
            self._reconcile_entries(entries)

    def _reconcile_entries(self, entries: Iterable[AssetEntry]) -> None:
        incoming = tuple(entries)
        render_key = (self._current_directory, self._resource_root)
        if render_key == self._last_render_key and incoming == self._last_input_entries:
            return

        decorated: list[tuple[tuple[int, str, bool], str, AssetEntry]] = []
        for entry in incoming:
            iid = self._path_iids.get(entry.path) or self._iid_for_path(entry.path)
            previous = self._entries.get(iid)
            sort_key = (
                self._entry_sort_keys.get(iid)
                if render_key == self._last_render_key and previous == entry
                else None
            )
            if sort_key is None:
                relative_path = entry.path.relative_to(self._current_directory)
                sort_key = (
                    len(relative_path.parts),
                    relative_path.as_posix().casefold(),
                    not entry.is_folder,
                )
            decorated.append((sort_key, iid, entry))
        decorated.sort(key=lambda value: value[0])
        desired_entries: dict[str, AssetEntry] = {}
        desired_parents: dict[str, str] = {}
        desired_rows: dict[str, tuple[str, tuple[str, str]]] = {}
        desired_sort_keys: dict[str, tuple[int, str, bool]] = {}
        children_by_parent: dict[str, list[str]] = {}
        for sort_key, iid, entry in decorated:
            previous_parent = (
                self._entry_parents.get(iid)
                if render_key == self._last_render_key and iid in self._entries
                else None
            )
            parent_iid = (
                "asset-root"
                if previous_parent == ""
                else previous_parent
                if previous_parent is not None
                else self._iid_for_path(entry.path.parent)
            )
            if parent_iid != "asset-root" and parent_iid not in desired_entries:
                continue
            parent = "" if parent_iid == "asset-root" else parent_iid
            row = self._entry_rows.get(iid) if self._entries.get(iid) == entry else None
            values = row[1] if row is not None else (entry.kind, str(entry.logical_id or ""))
            desired_entries[iid] = entry
            desired_parents[iid] = parent
            desired_rows[iid] = row if row is not None else (entry.name, values)
            desired_sort_keys[iid] = sort_key
            children_by_parent.setdefault(parent, []).append(iid)

        desired_order = {parent: tuple(children) for parent, children in children_by_parent.items()}
        desired_indices = {
            iid: index for children in desired_order.values() for index, iid in enumerate(children)
        }
        desired_ids = set(desired_entries)
        stale_ids = set(self._entries) - desired_ids
        selected = self._tree.selection()
        selected_iid = selected[0] if selected else None

        # Treeview.delete() removes a subtree. Delete only stale subtree roots;
        # descendants are removed with the parent and are skipped in this loop.
        for iid in self._entries:
            if (
                iid in stale_ids
                and self._entry_parents.get(iid, "") not in stale_ids
                and self._tree.exists(iid)
            ):
                self._tree.delete(iid)

        working_orders = {
            parent: [
                iid for iid in old_order if iid in desired_ids and desired_parents[iid] == parent
            ]
            for parent, old_order in self._child_order.items()
        }
        reordered_parents: set[str] = set()
        for parent, children in desired_order.items():
            old_common = tuple(
                iid
                for iid in self._child_order.get(parent, ())
                if iid in desired_ids and desired_parents[iid] == parent
            )
            new_common = tuple(
                iid
                for iid in children
                if iid in self._entries and self._entry_parents.get(iid) == parent
            )
            if old_common != new_common:
                reordered_parents.add(parent)

        for _sort_key, iid, entry in decorated:
            if iid not in desired_entries:
                continue
            parent = desired_parents[iid]
            index = desired_indices[iid]
            previous = self._entries.get(iid)
            previous_parent = self._entry_parents.get(iid)
            tree_item_exists = previous is not None and self._tree.exists(iid)
            if not tree_item_exists:
                siblings = working_orders.setdefault(parent, [])
                insertion_index = min(index, len(siblings))
                if insertion_index == len(siblings):
                    self._tree.insert(
                        parent, "end", iid=iid, text=entry.name, values=desired_rows[iid][1]
                    )
                else:
                    self._tree.insert(
                        parent,
                        insertion_index,
                        iid=iid,
                        text=entry.name,
                        values=desired_rows[iid][1],
                    )
                siblings.insert(insertion_index, iid)
            elif previous_parent != parent:
                siblings = working_orders.setdefault(parent, [])
                insertion_index = min(index, len(siblings))
                if insertion_index == len(siblings):
                    self._tree.move(iid, parent, "end")
                else:
                    self._tree.move(iid, parent, insertion_index)
                siblings.insert(insertion_index, iid)

            if tree_item_exists and self._entry_rows.get(iid) != desired_rows[iid]:
                text, values = desired_rows[iid]
                self._tree.item(iid, text=text, values=values)

        # A changed relative order is rare for path-sorted rows. When it occurs,
        # reconcile only that parent's sequence and leave every other branch alone.
        for parent in reordered_parents:
            for index, iid in enumerate(desired_order[parent]):
                if self._tree.index(iid) != index:
                    self._tree.move(iid, parent, index)
            working_orders[parent] = list(desired_order[parent])

        self._entries = desired_entries
        self._entry_parents = desired_parents
        self._entry_rows = desired_rows
        self._entry_sort_keys = desired_sort_keys
        self._child_order = desired_order
        self._path_iids = {self._current_directory: "asset-root"}
        self._path_iids.update((entry.path, iid) for iid, entry in desired_entries.items())
        self._last_render_key = render_key
        self._last_input_entries = incoming
        if selected_iid is not None and selected_iid in desired_entries:
            self._selected_entry = desired_entries[selected_iid]
            if self._tree.selection() != (selected_iid,):
                self._tree.selection_set(selected_iid)
        else:
            self._selected_entry = None
            current_selection = self._tree.selection()
            if current_selection:
                self._tree.selection_remove(current_selection)

    def _iid_for_path(self, path: Path) -> str:
        if path == self._current_directory:
            return "asset-root"
        return f"asset:{path.as_posix()}"

    def navigate_up(self) -> None:
        if self._current_directory == self._root_directory:
            return
        self._current_directory = self._current_directory.parent
        self._path_iids = {self._current_directory: "asset-root"}
        self._path_var.set(str(self._current_directory))
        self.refresh()

    def _accept_scan(self, result: AssetScanResult) -> None:
        if accept_scan_result(result, current_generation=self._generation):
            self.render_entries(result.entries)

    def _on_select(self, _event: Any = None) -> None:
        selection = self._tree.selection()
        self._selected_entry = self._entries.get(selection[0]) if selection else None

    def _on_press_for_drag(self, event: Any) -> None:
        self._drag_start = (event.x_root, event.y_root)
        row = self._tree.identify_row(event.y)
        self._drag_entry = self._entries.get(row)

    def _on_release_for_drag(self, event: Any) -> None:
        start = self._drag_start
        entry = self._drag_entry
        self._drag_start = None
        self._drag_entry = None
        if start is None or entry is None or self._on_drop is None or entry.is_folder:
            return
        dx, dy = event.x_root - start[0], event.y_root - start[1]
        if dx * dx + dy * dy < _DRAG_THRESHOLD_SQ:
            return  # a plain click/select, not a drag
        self._on_drop(entry, event.x_root, event.y_root)

    def _on_activate(self, _event: Any = None) -> str:
        entry = self._selected_entry
        if entry is None:
            return "break"
        if entry.is_folder:
            self._current_directory = entry.path
            self._path_iids = {self._current_directory: "asset-root"}
            self._path_var.set(str(self._current_directory))
            self.refresh()
        elif self._on_open is not None:
            self._on_open(entry)
        return "break"


def _iter_directory(directory: Path) -> tuple[Path, ...]:
    return tuple(directory.rglob("*"))
