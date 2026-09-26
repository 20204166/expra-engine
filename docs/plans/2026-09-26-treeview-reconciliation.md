# Shared Treeview Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share retained `ttk.Treeview` row mutations between the asset browser and scene hierarchy without merging their domain behavior.

**Architecture:** Add an immutable row snapshot and a stateless reconciler in `ui/tree_reconciliation.py`. Panels keep their own row collection, sorting, asset/entity mapping, selection, and callbacks; the reconciler owns stale-subtree deletion, inserts, moves, changed-row updates, and minimal sibling reordering.

**Tech Stack:** Python 3.12, Tk/ttk, pytest.

---

## File Map

- Create `src/expra_engine/ui/tree_reconciliation.py`: `TreeRow` and `reconcile_treeview`.
- Create `tests/test_tree_reconciliation.py`: a small Treeview test double and behavior tests.
- Modify `src/expra_engine/ui/hierarchy.py` and `asset_browser.py` to delegate mutations.
- Keep `tests/test_editor_ui.py` as the real-Tk integration coverage for both panels.

### Task 1: Specify the Shared Row Contract

**Files:** Create `tests/test_tree_reconciliation.py`.

- [x] **Step 1: Write behavior tests first.** Define desired rows as ordered `(iid, TreeRow)` pairs. Cover initial nested insertion, changed text/values/tags, stale subtree deletion, a surviving child whose former parent disappears, sibling reorder, and unchanged input producing zero mutations. Load the not-yet-created API inside a test helper and convert `ModuleNotFoundError`/missing symbols to `pytest.fail`, so the red run is an assertion failure rather than collection error.

```python
desired = (
    ("parent", TreeRow(parent="", text="Parent")),
    ("child", TreeRow(parent="parent", text="Child")),
)
result = reconcile_treeview(tree, {}, desired)
assert result["child"].parent == "parent"
assert tree.parent("child") == "parent"
```

- [x] **Step 2: Prove the test is red.** Run `pytest tests/test_tree_reconciliation.py -q`. Expected: the tests fail with the explicit “shared tree reconciler is not implemented” assertion.

### Task 2: Implement the Reconciler

**Files:** Create `src/expra_engine/ui/tree_reconciliation.py`.

- [x] **Step 1: Add the minimal API.** Define `TreeRow(parent: str, text: str, values: tuple[Any, ...] = (), tags: tuple[str, ...] = ())` and `reconcile_treeview(tree, previous: Mapping[str, TreeRow], desired: Sequence[tuple[str, TreeRow]]) -> dict[str, TreeRow]`.
- [x] **Step 2: Implement structural updates.** Delete only stale subtree roots; insert missing rows and rows removed indirectly with a stale ancestor; move rows whose parent/order changed; update row content only when it differs. Use a longest-in-order stable subset when a sibling sequence changes, and return the ordered desired snapshot.
- [x] **Step 3: Run `pytest tests/test_tree_reconciliation.py -q`.** Expected: all new helper tests pass.

### Task 3: Migrate the Scene Hierarchy

**Files:** Modify `src/expra_engine/ui/hierarchy.py`.

- [x] **Step 1:** Keep `_collect_entities`, scene preorder, selection, and callbacks unchanged. Convert each collected row to `TreeRow` and pass the ordered rows plus prior snapshot to `reconcile_treeview`.
- [x] **Step 2:** Run `pytest tests/test_tree_reconciliation.py tests/test_editor_ui.py -q`. Expected: helper tests and hierarchy/asset Tk tests pass, including stable selection, expansion, reparenting, and no-op mutation counts.

### Task 4: Migrate the Asset Browser

**Files:** Modify `src/expra_engine/ui/asset_browser.py`.

- [x] **Step 1:** Keep path IDs, `AssetEntry` maps, path-depth ordering, navigation, and selection updates panel-owned. Delegate only Treeview row mutations to the shared reconciler.
- [x] **Step 2:** Run `pytest tests/test_tree_reconciliation.py tests/test_editor_ui.py tests/test_editor_assets.py -q`. Expected: all pass, including the test where a child remains visible after its parent branch is removed.

### Task 5: Final Checks

- [x] Run `pytest tests/test_tree_reconciliation.py tests/test_editor_ui.py tests/test_editor_assets.py -q`.
- [x] Run Ruff on the new module, both panels, and new tests; then run `git diff --check`.
- [x] Review `git diff` to confirm panel-specific ordering/selection stayed in the panels and no unrelated UI files changed.
