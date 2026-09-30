"""Qt asset browser -- same behaviour and public surface as ``ui.asset_browser.AssetBrowserPanel``.

All scan, reconcile, selection and navigation logic lives in the shared
``AssetBrowserCore``; this module only builds Qt widgets and forwards events.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.editor.asset_browser_core import AssetBrowserCore
from expra_engine.editor.assets import AssetEntry
from expra_engine.editor.qt.tree_adapter import EventTree, QtTreeAdapter
from expra_engine.observability import ObservabilityWatcher
from expra_engine.ui.styles import COLORS


class AssetBrowserPanel(AssetBrowserCore, QWidget):
    """Browse project assets while exposing logical IDs to editor actions."""

    def __init__(
        self,
        parent: Any = None,
        *,
        root_directory: Path,
        resource_root: Path | None = None,
        coordinator: AppCoordinator | None = None,
        observer: ObservabilityWatcher | None = None,
        colors: dict[str, str] | None = None,
        on_open: Callable[[AssetEntry], None] | None = None,
        on_drop: Callable[[AssetEntry, int, int], None] | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._colors = colors or COLORS
        self._init_browser_state(
            root_directory=root_directory,
            resource_root=resource_root,
            coordinator=coordinator,
            observer=observer,
            on_open=on_open,
            on_drop=on_drop,
        )
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("ASSETS"))
        header.addStretch(1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(lambda *_a: self.refresh())
        up_button = QPushButton("Up")
        up_button.clicked.connect(lambda *_a: self.navigate_up())
        header.addWidget(up_button)
        header.addWidget(refresh_button)
        layout.addLayout(header)
        self._path_label = QLabel()
        layout.addWidget(self._path_label)

        self._widget = EventTree()
        self._widget.setColumnCount(2)
        self._widget.setHeaderLabels(["Name", "Type"])
        self._widget.setHeaderHidden(False)
        self._tree = QtTreeAdapter(self._widget, columns=("kind", "logical_id"))
        self._widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._widget.itemSelectionChanged.connect(self._on_select)
        self._widget.itemDoubleClicked.connect(lambda *_a: self._on_activate())
        self._widget.on_activate = self._on_activate
        self._widget.on_press = self._on_press_for_drag
        self._widget.on_release = self._on_release_for_drag
        layout.addWidget(self._widget)
        self._show_path(str(self._current_directory))

    def _show_path(self, text: str) -> None:
        self._path_label.setText(text)

    def _on_press_for_drag(self, x: int, y: int) -> None:
        self._begin_drag(self._tree.identify_row(y), *self._global(x, y))

    def _on_release_for_drag(self, x: int, y: int) -> None:
        self._end_drag(*self._global(x, y))

    def _global(self, x: int, y: int) -> tuple[int, int]:
        from PySide6.QtCore import QPoint

        point = self._widget.viewport().mapToGlobal(QPoint(x, y))
        return point.x(), point.y()

    def _on_activate(self) -> None:
        self._activate_selected()


__all__ = ["AssetBrowserPanel"]
