"""Toolkit-independent asset browser logic behind the Qt asset browser panel.

Owns scan/refresh generations, row reconciliation, selection retention and
directory navigation. Frontends supply a tree-shaped ``self._tree`` (``QtTreeAdapter``) and a
``_show_path`` hook; everything else is shared.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.editor.assets import (
    AssetEntry,
    AssetScanRequest,
    AssetScanResult,
    accept_scan_result,
    iter_project_paths,
    scan_directory,
)
from expra_engine.observability import ObservabilityWatcher, observe_stage
from expra_engine.ui.tree_reconciliation import TreeRow, reconcile_tree_rows

DRAG_THRESHOLD_SQ = 16  # 4px, squared -- avoids a sqrt on every motion event


def _iter_directory(directory: Path) -> tuple[Path, ...]:
    return iter_project_paths(directory)


class AssetBrowserCore:
    _tree: Any

    def _init_browser_state(
        self,
        *,
        root_directory: Path,
        resource_root: Path | None,
        coordinator: AppCoordinator | None,
        observer: ObservabilityWatcher | None,
        on_open: Callable[[AssetEntry], None] | None,
        on_drop: Callable[[AssetEntry, int, int], None] | None,
    ) -> None:
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
        self._row_state: dict[str, TreeRow] = {}
        self._entry_sort_keys: dict[str, tuple[int, str, bool]] = {}
        self._path_iids: dict[Path, str] = {self._current_directory: "asset-root"}
        self._last_render_key: tuple[Path, Path] | None = None
        self._last_input_entries: tuple[AssetEntry, ...] | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_entry: AssetEntry | None = None

    def _show_path(self, text: str) -> None:
        raise NotImplementedError

    def _begin_drag(self, row: str, x: int, y: int) -> None:
        self._drag_start = (x, y)
        self._drag_entry = self._entries.get(row)

    def _end_drag(self, x: int, y: int) -> None:
        start = self._drag_start
        entry = self._drag_entry
        self._drag_start = None
        self._drag_entry = None
        if start is None or entry is None or self._on_drop is None or entry.is_folder:
            return
        dx, dy = x - start[0], y - start[1]
        if dx * dx + dy * dy < DRAG_THRESHOLD_SQ:
            return  # a plain click/select, not a drag
        self._on_drop(entry, x, y)

    def _activate_selected(self) -> None:
        entry = self._selected_entry
        if entry is None:
            return
        if entry.is_folder:
            self._current_directory = entry.path
            self._path_iids = {self._current_directory: "asset-root"}
            self._show_path(str(self._current_directory))
            self.refresh()
        elif self._on_open is not None:
            self._on_open(entry)

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
        self._show_path(str(self._current_directory))
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
        desired_rows: dict[str, TreeRow] = {}
        desired_sort_keys: dict[str, tuple[int, str, bool]] = {}
        for sort_key, iid, entry in decorated:
            previous_row = (
                self._row_state.get(iid)
                if render_key == self._last_render_key and iid in self._entries
                else None
            )
            previous_parent = previous_row.parent if previous_row is not None else None
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
            values = (entry.kind, str(entry.logical_id or ""))
            desired_entries[iid] = entry
            desired_rows[iid] = TreeRow(parent=parent, text=entry.name, values=values)
            desired_sort_keys[iid] = sort_key

        selected = self._tree.selection()
        selected_iid = selected[0] if selected else None
        desired_tree_rows = tuple(
            (iid, desired_rows[iid]) for _sort_key, iid, _entry in decorated if iid in desired_rows
        )
        self._row_state = reconcile_tree_rows(self._tree, self._row_state, desired_tree_rows)

        self._entries = desired_entries
        self._entry_sort_keys = desired_sort_keys
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
        self._show_path(str(self._current_directory))
        self.refresh()

    def _accept_scan(self, result: AssetScanResult) -> None:
        if accept_scan_result(result, current_generation=self._generation):
            self.render_entries(result.entries)

    def _on_select(self, _event: Any = None) -> None:
        selection = self._tree.selection()
        self._selected_entry = self._entries.get(selection[0]) if selection else None
