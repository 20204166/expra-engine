"""Retained-tree contract adapter over QTreeWidget.

``reconcile_tree_rows`` (``expra_engine.ui.tree_reconciliation``) is the shared,
tested row-diffing algorithm used by the hierarchy and asset browser. This
adapter maps that small shared tree contract and panel selection operations to
``QTreeWidget``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

_IID_ROLE = int(Qt.ItemDataRole.UserRole)
_VALUES_ROLE = _IID_ROLE + 1
_TAGS_ROLE = _IID_ROLE + 2


def _child(item: QTreeWidgetItem, index: int) -> QTreeWidgetItem:
    child = item.child(index)
    assert child is not None  # index is always within childCount()
    return child


class EventTree(QTreeWidget):
    """QTreeWidget that reports raw press/release/Return for the panels' selection handling."""

    def __init__(self) -> None:
        super().__init__()
        self.on_press: Callable[[int, int], None] | None = None
        self.on_release: Callable[[int, int], None] | None = None
        self.on_activate: Callable[[], None] | None = None

    def mousePressEvent(self, event: Any) -> None:
        position = event.position().toPoint()
        if self.on_press is not None and event.button() == Qt.MouseButton.LeftButton:
            self.on_press(position.x(), position.y())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        position = event.position().toPoint()
        super().mouseReleaseEvent(event)
        if self.on_release is not None and event.button() == Qt.MouseButton.LeftButton:
            self.on_release(position.x(), position.y())

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.on_activate is not None:
            self.on_activate()
            event.accept()
            return
        super().keyPressEvent(event)


class QtTreeAdapter:
    def __init__(
        self,
        tree: QTreeWidget,
        *,
        tag_colors: dict[str, str] | None = None,
        columns: tuple[str, ...] = (),
    ) -> None:
        self.widget = tree
        self._columns = columns
        self._items: dict[str, QTreeWidgetItem] = {}
        self._tag_colors = dict(tag_colors or {})
        tree.setHeaderHidden(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    # -- structure ----------------------------------------------------

    def _parent_item(self, parent: str) -> QTreeWidgetItem:
        return self.widget.invisibleRootItem() if not parent else self._items[parent]

    def exists(self, iid: str) -> bool:
        return iid in self._items

    def get_children(self, parent: str = "") -> tuple[str, ...]:
        item = self._parent_item(parent)
        return tuple(_child(item, i).data(0, _IID_ROLE) for i in range(item.childCount()))

    def parent(self, iid: str) -> str:
        parent = self._items[iid].parent()
        return "" if parent is None else str(parent.data(0, _IID_ROLE))

    def insert(
        self,
        parent: str,
        index: int,
        *,
        iid: str,
        text: str = "",
        values: tuple[Any, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> str:
        item = QTreeWidgetItem()
        item.setData(0, _IID_ROLE, iid)
        self._items[iid] = item
        self._apply(item, text=text, values=values, tags=tags)
        self._parent_item(parent).insertChild(index, item)
        return iid

    def move(self, iid: str, parent: str, index: int) -> None:
        item = self._items[iid]
        old_parent = item.parent() or self.widget.invisibleRootItem()
        old_parent.takeChild(old_parent.indexOfChild(item))
        self._parent_item(parent).insertChild(index, item)

    def delete(self, iid: str) -> None:
        item = self._items.get(iid)
        if item is None:
            return
        for descendant in self._descendants(item):
            self._items.pop(descendant.data(0, _IID_ROLE), None)
        self._items.pop(iid, None)
        parent = item.parent() or self.widget.invisibleRootItem()
        parent.removeChild(item)

    def item(self, iid: str, option: str | None = None, **changes: Any) -> Any:
        item = self._items[iid]
        if option is not None:
            if option == "open":
                return item.isExpanded()
            if option == "text":
                return item.text(0)
            if option == "values":
                return item.data(0, _VALUES_ROLE) or ()
            if option == "tags":
                return item.data(0, _TAGS_ROLE) or ()
            raise KeyError(option)
        if "open" in changes:
            item.setExpanded(bool(changes.pop("open")))
        if changes:
            self._apply(
                item,
                text=changes.get("text"),
                values=changes.get("values"),
                tags=changes.get("tags"),
            )
        return None

    def set(self, iid: str, column: str) -> Any:
        values = self._items[iid].data(0, _VALUES_ROLE) or ()
        return values[self._columns.index(column)]

    def _apply(
        self,
        item: QTreeWidgetItem,
        *,
        text: str | None,
        values: tuple[Any, ...] | None,
        tags: tuple[str, ...] | None,
    ) -> None:
        if text is not None:
            item.setText(0, text)
        if values is not None:
            item.setData(0, _VALUES_ROLE, tuple(values))
            if values:
                item.setText(1, str(values[0]))
        if tags is not None:
            item.setData(0, _TAGS_ROLE, tuple(tags))
            color = next((self._tag_colors[t] for t in tags if t in self._tag_colors), None)
            item.setForeground(0, QBrush(QColor(color)) if color else QBrush())

    def _descendants(self, item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
        for i in range(item.childCount()):
            child = _child(item, i)
            yield child
            yield from self._descendants(child)

    def _in_tree_order(self) -> Iterator[QTreeWidgetItem]:
        yield from self._descendants(self.widget.invisibleRootItem())

    # -- selection ----------------------------------------------------

    def selection(self) -> tuple[str, ...]:
        selected = set(map(id, self.widget.selectedItems()))
        if not selected:
            return ()
        return tuple(
            item.data(0, _IID_ROLE) for item in self._in_tree_order() if id(item) in selected
        )

    @staticmethod
    def _as_ids(iids: str | tuple[str, ...]) -> tuple[str, ...]:
        return (iids,) if isinstance(iids, str) else tuple(iids)

    def selection_set(self, iids: str | tuple[str, ...]) -> None:
        """Replace the selection with ``iids`` (single change notification).

        Reports one selection change, not a clear followed by a set.
        """
        ids = self._as_ids(iids)
        items = [self._items[iid] for iid in ids]  # KeyError for a missing row, like Tcl
        before = self.selection()
        was_blocked = self.widget.blockSignals(True)
        try:
            self.widget.clearSelection()
            for item in items:
                item.setSelected(True)
        finally:
            self.widget.blockSignals(was_blocked)
        if not was_blocked and self.selection() != before:
            self.widget.itemSelectionChanged.emit()

    def selection_remove(self, iids: str | tuple[str, ...]) -> None:
        for iid in self._as_ids(iids):
            item = self._items.get(iid)
            if item is not None:
                item.setSelected(False)

    def focus(self, iid: str) -> None:
        self.widget.setCurrentItem(
            self._items[iid], 0, self.widget.selectionModel().SelectionFlag.NoUpdate
        )

    def see(self, iid: str) -> None:
        self.widget.scrollToItem(self._items[iid])

    def identify_row(self, y: int, x: int = 0) -> str:
        item = self.widget.itemAt(QPoint(x, y))
        return item.data(0, _IID_ROLE) if item is not None else ""
