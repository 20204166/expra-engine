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
from expra_engine.ui.styles import (
    COLORS,
    FONTS,
    SPACING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_TREEVIEW,
)


class AssetBrowserPanel(tk.Frame):
    """Browse project assets while exposing logical IDs to editor actions."""

    def __init__(
        self,
        parent: Any,
        *,
        root_directory: Path,
        resource_root: Path | None = None,
        coordinator: AppCoordinator | None = None,
        colors: dict[str, str] | None = None,
        on_open: Callable[[AssetEntry], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._coordinator = coordinator
        self._on_open = on_open
        self._root_directory = Path(root_directory).resolve()
        self._resource_root = Path(resource_root or root_directory).resolve()
        self._current_directory = self._root_directory
        self._generation = 0
        self._selected_entry: AssetEntry | None = None
        self._entries: dict[str, AssetEntry] = {}

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
        self._path_var.set(str(self._current_directory))

    @property
    def root_directory(self) -> Path:
        return self._root_directory

    @property
    def current_directory(self) -> Path:
        return self._current_directory

    def set_root_directory(self, directory: Path) -> None:
        """Switch the browser to a new project asset root."""
        self._root_directory = directory.resolve()
        self._resource_root = self._root_directory
        self._current_directory = self._root_directory
        self._selected_entry = None
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
        self._entries.clear()
        for item in self._tree.get_children(""):
            self._tree.delete(item)
        ordered = sorted(
            entries,
            key=lambda entry: (
                len(entry.path.relative_to(self._current_directory).parts),
                entry.path.relative_to(self._current_directory).as_posix().casefold(),
                not entry.is_folder,
            ),
        )
        for entry in ordered:
            iid = self._iid_for_path(entry.path)
            parent_iid = self._iid_for_path(entry.path.parent)
            if parent_iid != "asset-root" and not self._tree.exists(parent_iid):
                continue
            self._entries[iid] = entry
            self._tree.insert(
                "" if parent_iid == "asset-root" else parent_iid,
                "end",
                iid=iid,
                text=entry.name,
                values=(entry.kind, str(entry.logical_id or "")),
            )
        self._selected_entry = None

    def _iid_for_path(self, path: Path) -> str:
        if path == self._current_directory:
            return "asset-root"
        return f"asset:{path.as_posix()}"

    def navigate_up(self) -> None:
        if self._current_directory == self._root_directory:
            return
        self._current_directory = self._current_directory.parent
        self._path_var.set(str(self._current_directory))
        self.refresh()

    def _accept_scan(self, result: AssetScanResult) -> None:
        if accept_scan_result(result, current_generation=self._generation):
            self.render_entries(result.entries)

    def _on_select(self, _event: Any = None) -> None:
        selection = self._tree.selection()
        self._selected_entry = self._entries.get(selection[0]) if selection else None

    def _on_activate(self, _event: Any = None) -> str:
        entry = self._selected_entry
        if entry is None:
            return "break"
        if entry.is_folder:
            self._current_directory = entry.path
            self._path_var.set(str(self._current_directory))
            self.refresh()
        elif self._on_open is not None:
            self._on_open(entry)
        return "break"


def _iter_directory(directory: Path) -> tuple[Path, ...]:
    return tuple(directory.rglob("*"))
