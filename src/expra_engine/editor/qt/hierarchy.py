"""Qt hierarchy panel.

Row projection (``collect_entity_rows`` / ``collect_world_rows``) and row
reconciliation (``reconcile_tree_rows``) are the toolkit-independent shared
implementations; this module only builds the widget and wires events.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from expra_engine.core.scene import Scene
from expra_engine.core.world import World
from expra_engine.editor.hierarchy_rows import collect_entity_rows, collect_world_rows
from expra_engine.editor.qt.action_widget import QtActionWidget
from expra_engine.editor.qt.tree_adapter import EventTree, QtTreeAdapter
from expra_engine.ui.styles import COLORS
from expra_engine.ui.tree_reconciliation import TreeRow, reconcile_tree_rows

_DRAG_THRESHOLD_SQ = 16  # 4px, squared


class HierarchyPanel(QWidget):
    """Display a scene's entity hierarchy and expose editor actions."""

    _collect_world_rows = staticmethod(collect_world_rows)
    _collect_entities = staticmethod(collect_entity_rows)

    def __init__(
        self,
        parent: Any = None,
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
        on_open_source: Callable[[], None] | None = None,
        on_make_unique: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        c = colors or COLORS
        self._colors = c
        self._actions = actions
        self._on_select = on_select
        self._on_create = on_create
        self._on_add_level = on_add_level
        self._on_create_connection = on_create_connection
        self._on_open_level = on_open_level
        self._on_delete = on_delete
        self._on_reparent = on_reparent
        self._on_open_source = on_open_source
        self._on_make_unique = on_make_unique
        self._scene: Scene | None = None
        self._entity_ids: list[str] = []
        self._row_state: dict[str, TreeRow] = {}
        self._selected_ids: tuple[str, ...] = ()
        self._drag_start: tuple[int, int] | None = None
        self._drag_ids: tuple[str, ...] = ()
        self._is_world = False
        self._world_document: World | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self._header_label = QLabel("HIERARCHY")
        header.addWidget(self._header_label)
        header.addStretch(1)
        self._add_button = QPushButton("+  Add")
        self._world_add_button = QPushButton("+  Add Level")
        self._world_connection_button = QPushButton("+  Connect")
        self._delete_button = QPushButton("Delete")
        for button, action_id, handler in (
            (self._add_button, "add_entity", self._handle_create),
            (self._world_add_button, "add_world_level", self._handle_add_world_level),
            (self._world_connection_button, "create_world_connection", self._handle_world_connection),
            (self._delete_button, "delete_entity", self._handle_delete),
        ):
            if actions is not None:
                actions.bind(QtActionWidget(button), action_id)
            else:
                button.clicked.connect(lambda *_a, h=handler: h())
        self._world_add_button.setVisible(False)
        self._world_connection_button.setVisible(False)
        header.addWidget(self._add_button)
        header.addWidget(self._world_add_button)
        header.addWidget(self._world_connection_button)
        layout.addLayout(header)

        self._widget = EventTree()
        self._tree = QtTreeAdapter(self._widget, tag_colors={"disabled": c["ink_3"]})
        self._widget.itemSelectionChanged.connect(self._on_tree_select)
        self._widget.on_press = self._on_press_for_drag
        self._widget.on_release = self._on_release_for_drag
        self._widget.on_activate = self._on_tree_activate
        layout.addWidget(self._widget)

        self._open_source_button = QPushButton("Open Source")
        self._make_unique_button = QPushButton("Make Unique")
        self._open_source_button.setEnabled(False)
        self._make_unique_button.setEnabled(False)
        self._open_source_button.clicked.connect(self._handle_open_source)
        self._make_unique_button.clicked.connect(self._handle_make_unique)

        footer = QHBoxLayout()
        footer.addWidget(self._open_source_button)
        footer.addWidget(self._make_unique_button)
        footer.addStretch(1)
        footer.addWidget(self._delete_button)
        layout.addLayout(footer)

    def render(self, scene: Scene | World | None) -> None:
        """Reconcile only changed rows while retaining stable tree state."""
        selected = self._selected_ids
        world = scene if isinstance(scene, World) else None
        self._is_world = world is not None
        self._scene = scene if isinstance(scene, Scene) else None
        self._header_label.setText("WORLD" if self._is_world else "HIERARCHY")
        if world is not None:
            self._add_button.setVisible(False)
            self._world_add_button.setVisible(True)
            self._world_connection_button.setVisible(True)
            self._add_button.setEnabled(False)
            self._world_add_button.setEnabled(True)
            self._delete_button.setEnabled(False)
            if self._actions is not None:
                self._actions.set_enabled("add_entity", False)
                self._actions.set_enabled("add_world_level", True)
                self._actions.set_enabled("create_world_connection", True)
                self._actions.set_enabled("delete_entity", False)
                self._actions.set_enabled("duplicate_selection", False)
            if self._world_document is world:
                self.select_many(tuple(item for item in selected if item in self._row_state))
                return
            self._world_document = world
            incoming = collect_world_rows(world)
        else:
            self._world_document = None
            self._world_add_button.setVisible(False)
            self._world_connection_button.setVisible(False)
            self._add_button.setVisible(True)
            self._add_button.setEnabled(True)
            if self._actions is not None:
                self._actions.set_enabled("add_world_level", False)
                self._actions.set_enabled("create_world_connection", False)
            self._delete_button.setEnabled(True)
            incoming = collect_entity_rows(scene if isinstance(scene, Scene) else None)
        desired = tuple(
            (entity_id, TreeRow(parent=parent, text=text, tags=tags))
            for entity_id, parent, text, tags in incoming
        )
        self._widget.blockSignals(True)
        try:
            self._row_state = reconcile_tree_rows(self._tree, self._row_state, desired)
        finally:
            self._widget.blockSignals(False)
        self._entity_ids = [entity_id for entity_id, _parent, _text, _tags in incoming]
        incoming_ids = set(self._row_state)
        kept = tuple(entity_id for entity_id in selected if entity_id in incoming_ids)
        self.select_many(kept if kept else ())

    def select(self, entity_id: str | None) -> None:
        """Select a single entity, or clear selection when ``None``."""
        self.select_many((entity_id,) if entity_id is not None else ())

    def select_many(self, entity_ids: tuple[str, ...]) -> None:
        """Select exactly ``entity_ids`` (deduped, order-preserving)."""
        ids = tuple(dict.fromkeys(entity_ids))
        current = self._tree.selection()
        valid = tuple(entity_id for entity_id in ids if entity_id in self._row_state)
        self._widget.blockSignals(True)
        try:
            if not valid:
                self._selected_ids = ()
                if current:
                    self._tree.selection_remove(current)
                return
            if current != valid:
                self._tree.selection_remove(current)
                try:
                    self._tree.selection_set(valid)
                except KeyError:
                    # A row may have disappeared outside reconciliation. Keep the
                    # retained-state fast path, but verify against the tree on this error.
                    valid = tuple(entity_id for entity_id in valid if self._tree.exists(entity_id))
                    if valid:
                        self._tree.selection_set(valid)
            self._selected_ids = valid
            if not valid:
                self._refresh_linked_actions()
                return
            self._tree.focus(valid[0])
            self._tree.see(valid[0])
        finally:
            self._widget.blockSignals(False)
        self._refresh_linked_actions()

    def _on_tree_select(self) -> None:
        selection = self._tree.selection()
        if selection == self._selected_ids:
            return
        self._selected_ids = selection
        self._refresh_linked_actions()
        if self._on_select is not None:
            self._on_select(self._selected_ids)

    def _on_tree_activate(self) -> None:
        if self._selected_ids:
            selected = self._selected_ids[0]
            if self._is_world and selected.startswith("level:") and self._on_open_level:
                self._on_open_level(selected.removeprefix("level:"))
            else:
                self._tree.item(selected, open=True)

    def _on_press_for_drag(self, x: int, y: int) -> None:
        self._drag_start = (x, y)
        row = self._tree.identify_row(y)
        if row and row in self._selected_ids:
            self._drag_ids = self._selected_ids
        elif row:
            self._drag_ids = (row,)
        else:
            self._drag_ids = ()

    def _on_release_for_drag(self, x: int, y: int) -> None:
        start = self._drag_start
        ids = self._drag_ids
        self._drag_start = None
        self._drag_ids = ()
        if start is None or not ids or self._on_reparent is None or self._is_world:
            return
        dx, dy = x - start[0], y - start[1]
        if dx * dx + dy * dy < _DRAG_THRESHOLD_SQ:
            return  # a plain click/select, not a drag
        target_row = self._tree.identify_row(y)
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

    def _handle_open_source(self) -> None:
        if self._on_open_source is not None:
            self._on_open_source()

    def _handle_make_unique(self) -> None:
        if self._on_make_unique is not None:
            self._on_make_unique()

    def _refresh_linked_actions(self) -> None:
        first = self._selected_ids[0] if self._selected_ids else None
        linked = False
        if first is not None and self._scene is not None and not self._is_world:
            try:
                linked = self._scene.entity_origin(first).kind in ("materialized", "instance_root")
            except (KeyError, AttributeError):
                linked = False
        self._open_source_button.setEnabled(linked)
        self._make_unique_button.setEnabled(linked)


__all__ = ["HierarchyPanel"]
