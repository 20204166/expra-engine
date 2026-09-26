"""Shared structural reconciliation for retained Treeview rows."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TreeRow:
    """Domain-neutral content and parent snapshot for one Treeview row."""

    parent: str
    text: str
    values: tuple[Any, ...] = ()
    tags: tuple[str, ...] = ()


def reconcile_treeview(
    tree: Any,
    previous: Mapping[str, TreeRow],
    desired: Sequence[tuple[str, TreeRow]],
) -> dict[str, TreeRow]:
    """Apply the structural differences between previous and desired rows."""
    desired_rows = dict(desired)
    if tuple(previous.items()) == tuple(desired):
        return desired_rows

    desired_ids = set(desired_rows)
    stale_ids = set(previous) - desired_ids
    previous_children: dict[str, list[str]] = {}
    for iid, row in previous.items():
        previous_children.setdefault(row.parent, []).append(iid)

    stale_roots = [
        iid for iid, row in previous.items() if iid in stale_ids and row.parent not in stale_ids
    ]
    removed_with_stale_ancestor = set(stale_roots)
    stack = list(stale_roots)
    while stack:
        parent = stack.pop()
        for child in previous_children.get(parent, ()):
            if child not in removed_with_stale_ancestor:
                removed_with_stale_ancestor.add(child)
                stack.append(child)

    open_states: dict[str, bool] = {}
    for iid in desired_ids.intersection(removed_with_stale_ancestor):
        if tree.exists(iid):
            open_states[iid] = bool(tree.item(iid, "open"))

    for iid in stale_roots:
        if tree.exists(iid):
            tree.delete(iid)

    existing_ids = {iid for iid in desired_ids if tree.exists(iid)}

    children_by_parent: dict[str, list[str]] = {}
    for iid, row in desired:
        children_by_parent.setdefault(row.parent, []).append(iid)
    desired_indices = {
        iid: index for children in children_by_parent.values() for index, iid in enumerate(children)
    }
    working_orders: dict[str, list[str]] = {}
    for iid, row in previous.items():
        if iid in existing_ids and desired_rows[iid].parent == row.parent:
            working_orders.setdefault(row.parent, []).append(iid)

    for iid, row in desired:
        old_row = previous.get(iid)
        exists = iid in existing_ids
        index = desired_indices[iid]
        if not exists:
            siblings = working_orders.setdefault(row.parent, [])
            insertion_index = min(index, len(siblings))
            tree.insert(
                row.parent,
                insertion_index,
                iid=iid,
                text=row.text,
                values=row.values,
                tags=row.tags,
            )
            siblings.insert(insertion_index, iid)
        elif old_row is not None and old_row.parent != row.parent:
            siblings = working_orders.setdefault(row.parent, [])
            insertion_index = min(index, len(siblings))
            tree.move(iid, row.parent, insertion_index)
            siblings.insert(insertion_index, iid)

        if (
            exists
            and old_row is not None
            and (
                old_row.text != row.text or old_row.values != row.values or old_row.tags != row.tags
            )
        ):
            tree.item(iid, text=row.text, values=row.values, tags=row.tags)
        if not exists and open_states.get(iid, False):
            tree.item(iid, open=True)

    for parent, desired_children in children_by_parent.items():
        old_common = tuple(
            iid
            for iid in previous_children.get(parent, ())
            if iid in existing_ids and iid in desired_rows and desired_rows[iid].parent == parent
        )
        new_common = tuple(
            iid
            for iid in desired_children
            if iid in existing_ids
            and previous.get(iid) is not None
            and previous[iid].parent == parent
        )
        if old_common == new_common:
            continue

        current_children = working_orders.get(parent, [])
        current_positions = {iid: index for index, iid in enumerate(current_children)}
        stable_ids = _longest_in_order_subset(desired_children, current_positions)
        for index, iid in enumerate(desired_children):
            if iid not in stable_ids:
                current_index = current_children.index(iid)
                if current_index != index:
                    tree.move(iid, parent, index)
                    current_children.pop(current_index)
                    current_children.insert(index, iid)

    return desired_rows


def _longest_in_order_subset(
    desired: Sequence[str], current_positions: Mapping[str, int]
) -> set[str]:
    """Find a longest desired-order subsequence that already has that order."""
    sequence = [(iid, current_positions[iid]) for iid in desired if iid in current_positions]
    if not sequence:
        return set()

    tails: list[int] = []
    tail_indices: list[int] = []
    previous = [-1] * len(sequence)
    for index, (_iid, position) in enumerate(sequence):
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
