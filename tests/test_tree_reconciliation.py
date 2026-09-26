"""Behavior tests for the shared Treeview reconciliation helper."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Any

import pytest


class TreeviewDouble:
    """Small retained-tree model that records structural/content mutations."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.children: dict[str, list[str]] = {"": []}
        self.open_states: dict[str, bool] = {}
        self.calls = {"insert": 0, "delete": 0, "item": 0, "move": 0}
        self.get_children_calls = 0

    def insert(
        self,
        parent: str,
        index: int | str,
        *,
        iid: str,
        text: str,
        values: tuple[Any, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> str:
        self.calls["insert"] += 1
        siblings = self.children[parent]
        position = len(siblings) if index == "end" else int(index)
        siblings.insert(position, iid)
        self.rows[iid] = {
            "parent": parent,
            "text": text,
            "values": values,
            "tags": tags,
        }
        self.children[iid] = []
        self.open_states[iid] = False
        return iid

    def delete(self, *iids: str) -> None:
        self.calls["delete"] += 1
        for iid in iids:
            self._delete_subtree(iid)

    def _delete_subtree(self, iid: str) -> None:
        for child in tuple(self.children[iid]):
            self._delete_subtree(child)
        parent = self.rows[iid]["parent"]
        self.children[parent].remove(iid)
        del self.children[iid]
        del self.rows[iid]
        del self.open_states[iid]

    def move(self, iid: str, parent: str, index: int | str) -> None:
        self.calls["move"] += 1
        old_parent = self.rows[iid]["parent"]
        self.children[old_parent].remove(iid)
        siblings = self.children[parent]
        position = len(siblings) if index == "end" else int(index)
        siblings.insert(position, iid)
        self.rows[iid]["parent"] = parent

    def item(self, iid: str, option: str | None = None, **kwargs: Any) -> Any:
        if kwargs:
            self.calls["item"] += 1
            self.rows[iid].update(kwargs)
            if "open" in kwargs:
                self.open_states[iid] = kwargs["open"]
        if option is not None:
            if option == "open":
                return self.open_states[iid]
            return self.rows[iid][option]
        return dict(self.rows[iid])

    def exists(self, iid: str) -> bool:
        return iid in self.rows

    def parent(self, iid: str) -> str:
        return self.rows[iid]["parent"]

    def get_children(self, parent: str = "") -> tuple[str, ...]:
        self.get_children_calls += 1
        return tuple(self.children[parent])

    def clear_calls(self) -> None:
        for name in self.calls:
            self.calls[name] = 0
        self.get_children_calls = 0


def _load_api() -> tuple[type[Any], Callable[..., dict[str, Any]]]:
    try:
        module = import_module("expra_engine.ui.tree_reconciliation")
        return module.TreeRow, module.reconcile_treeview
    except (ImportError, AttributeError):
        pytest.fail("shared tree reconciler is not implemented", pytrace=False)


def test_reconciler_inserts_ordered_nested_rows() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    desired = (
        ("parent", TreeRow(parent="", text="Parent")),
        ("child", TreeRow(parent="parent", text="Child")),
    )

    result = reconcile_treeview(tree, {}, desired)

    assert list(result) == ["parent", "child"]
    assert result == dict(desired)
    assert tree.children[""] == ["parent"]
    assert tree.children["parent"] == ["child"]
    assert tree.calls == {"insert": 2, "delete": 0, "item": 0, "move": 0}
    assert tree.get_children_calls == 0


def test_reconciler_updates_only_changed_row_content() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {
        "asset": TreeRow(
            parent="",
            text="old.png",
            values=("Image", "assets://old.png"),
            tags=("old",),
        )
    }
    tree.insert(
        "",
        "end",
        iid="asset",
        text="old.png",
        values=("Image", "assets://old.png"),
        tags=("old",),
    )
    tree.clear_calls()
    desired = (
        (
            "asset",
            TreeRow(
                parent="",
                text="new.png",
                values=("Texture", "assets://new.png"),
                tags=("updated",),
            ),
        ),
    )

    result = reconcile_treeview(tree, previous, desired)

    assert result == dict(desired)
    assert tree.item("asset") == {
        "parent": "",
        "text": "new.png",
        "values": ("Texture", "assets://new.png"),
        "tags": ("updated",),
    }
    assert tree.calls == {"insert": 0, "delete": 0, "item": 1, "move": 0}


def test_reconciler_deletes_stale_subtree_and_reinserts_surviving_descendant() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {
        "root": TreeRow(parent="", text="Root"),
        "removed": TreeRow(parent="root", text="Removed"),
        "survivor": TreeRow(parent="removed", text="Survivor"),
    }
    tree.insert("", "end", iid="root", text="Root")
    tree.insert("root", "end", iid="removed", text="Removed")
    tree.insert("removed", "end", iid="survivor", text="Survivor")
    tree.clear_calls()
    desired = (
        ("root", TreeRow(parent="", text="Root")),
        ("survivor", TreeRow(parent="", text="Survivor")),
    )

    result = reconcile_treeview(tree, previous, desired)

    assert list(result) == ["root", "survivor"]
    assert not tree.exists("removed")
    assert tree.exists("survivor")
    assert tree.parent("survivor") == ""
    assert tree.get_children() == ("root", "survivor")
    assert tree.calls == {"insert": 1, "delete": 1, "item": 0, "move": 0}


def test_reconciler_preserves_expanded_state_of_reinserted_descendant() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {
        "removed": TreeRow(parent="", text="Removed"),
        "survivor": TreeRow(parent="removed", text="Survivor"),
        "grandchild": TreeRow(parent="survivor", text="Grandchild"),
    }
    tree.insert("", "end", iid="removed", text="Removed")
    tree.insert("removed", "end", iid="survivor", text="Survivor")
    tree.insert("survivor", "end", iid="grandchild", text="Grandchild")
    tree.item("survivor", open=True)
    tree.clear_calls()
    desired = (
        ("survivor", TreeRow(parent="", text="Survivor")),
        ("grandchild", TreeRow(parent="survivor", text="Grandchild")),
    )

    reconcile_treeview(tree, previous, desired)

    assert tree.item("survivor", "open") is True
    assert tree.calls == {"insert": 2, "delete": 1, "item": 1, "move": 0}


def test_reconciler_minimizes_sibling_reordering_moves() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {iid: TreeRow(parent="", text=iid) for iid in ("a", "b", "c", "d")}
    for iid in previous:
        tree.insert("", "end", iid=iid, text=iid)
    tree.clear_calls()
    desired = tuple((iid, previous[iid]) for iid in ("b", "c", "d", "a"))

    reconcile_treeview(tree, previous, desired)

    assert tree.children[""] == ["b", "c", "d", "a"]
    assert tree.calls == {"insert": 0, "delete": 0, "item": 0, "move": 1}
    assert tree.get_children_calls == 0


def test_reconciler_moves_row_when_its_parent_changes() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {
        "left": TreeRow(parent="", text="Left"),
        "right": TreeRow(parent="", text="Right"),
        "child": TreeRow(parent="left", text="Child"),
    }
    tree.insert("", "end", iid="left", text="Left")
    tree.insert("", "end", iid="right", text="Right")
    tree.insert("left", "end", iid="child", text="Child")
    tree.clear_calls()
    desired = (
        ("left", previous["left"]),
        ("right", previous["right"]),
        ("child", TreeRow(parent="right", text="Child")),
    )

    reconcile_treeview(tree, previous, desired)

    assert tree.children["left"] == []
    assert tree.children["right"] == ["child"]
    assert tree.calls == {"insert": 0, "delete": 0, "item": 0, "move": 1}
    assert tree.get_children_calls == 0


def test_unchanged_reconciliation_performs_no_tree_mutations() -> None:
    TreeRow, reconcile_treeview = _load_api()
    tree = TreeviewDouble()
    previous = {
        "parent": TreeRow(parent="", text="Parent"),
        "child": TreeRow(parent="parent", text="Child", values=("value",), tags=("tag",)),
    }
    tree.insert("", "end", iid="parent", text="Parent")
    tree.insert(
        "parent",
        "end",
        iid="child",
        text="Child",
        values=("value",),
        tags=("tag",),
    )
    tree.clear_calls()
    desired: Sequence[tuple[str, Any]] = tuple(previous.items())

    result = reconcile_treeview(tree, previous, desired)

    assert result == previous
    assert tree.calls == {"insert": 0, "delete": 0, "item": 0, "move": 0}
    assert tree.get_children_calls == 0
