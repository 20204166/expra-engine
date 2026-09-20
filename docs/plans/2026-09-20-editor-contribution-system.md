# Editor Contribution System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, backwards-compatible declarative editor contribution layer while preserving both existing coordinators and all current action IDs.

**Architecture:** Add the standalone `editor/contributions.py` module with explicit metadata, ownership, factories, and render-target resolution. Integrate it incrementally into `EditorWindow`; legacy direct wiring remains valid until each built-in is migrated. `ButtonCoordinator` and `UICoordinator` remain the execution and presentation-safety owners.

**Tech Stack:** Python 3.12, Tk/ttkbootstrap, dataclasses, typing protocols, unittest/pytest, Ruff, mypy, pyright.

---

## File Map

- Create: `src/expra_engine/editor/contributions.py` — context, specs, registry, factories, lifecycle ownership, and render-target registry.
- Modify: `src/expra_engine/ui/editor_window.py` — opt-in composition, built-in provider list, migrated surfaces, render adapter, and shutdown ordering.
- Modify: `src/expra_engine/ui/toolbar.py` — generic contribution-driven buttons while preserving existing style roles.
- Modify: `src/expra_engine/ui/styles.py` — only explicit semantic-role mapping additions, if required.
- Create: `tests/test_editor_contributions.py` — registry, compatibility, conflicts, lifecycle, and surface tests.
- Create: `tests/test_editor_render_targets.py` — target registration/removal and safety tests.
- Modify: `tests/test_editor_ui.py` — real-Tk or composition-root regression coverage where existing fixtures support it.
- Modify: `tests/test_button_coordinator.py` and `tests/test_ui_coordinator.py` only when a missing regression is proven; preserve existing tests.
- Create: `docs/audits/2026-09-20-editor-contribution-edge-cases.md` — evidence matrix from the local Ursina, PPB, and reference Expra test archives.

Do not include the pre-existing unstaged export/UI changes in these commits unless explicitly requested; inspect them before editing shared files.

## Phase 1: Foundation

### Task 1: Define contribution metadata and context

**Files:** `src/expra_engine/editor/contributions.py`, `tests/test_editor_contributions.py`

- [ ] Write failing tests for stable action IDs, initial enabled state, menu placement, toolbar style roles, shortcut metadata, and explicit context dependencies.
- [ ] Run `pytest tests/test_editor_contributions.py -q`; confirm failure because the module/types do not exist.
- [ ] Add frozen/slot dataclasses and small protocols without registration side effects.
- [ ] Run the focused tests and Ruff.
- [ ] Commit: `feat: define editor contribution metadata`.

### Task 2: Implement transactional registry ownership

**Files:** `src/expra_engine/editor/contributions.py`, `tests/test_editor_contributions.py`

- [ ] Add failing tests for registration through `ButtonCoordinator`, duplicate IDs, empty features, duplicate normalized shortcuts, invalid references, all-or-nothing failure, owned unregister, and repeated unregister.
- [ ] Run the focused tests and verify expected failures.
- [ ] Implement explicit `ContributionRegistry` validation and ownership records; delegate action execution/state to `ButtonCoordinator`.
- [ ] Test that direct legacy coordinator registration remains unchanged.
- [ ] Commit: `feat: add opt-in editor contribution registry`.

### Task 3: Add shortcut and surface factories

**Files:** `src/expra_engine/editor/contributions.py`, `tests/test_editor_contributions.py`

- [ ] Write failing tests proving menu, toolbar, and shortcut routes invoke one action callback once and disabled actions are rejected on every route.
- [ ] Implement deterministic shortcut normalization and conflict detection; route all activation through `ButtonCoordinator.dispatch()`.
- [ ] Implement menu/toolbar construction seams using injected Tk-like factories so tests do not require a display.
- [ ] Commit: `feat: wire declarative editor action surfaces`.

## Phase 2: Presentation and Lifecycle

### Task 4: Add render-target registry

**Files:** `src/expra_engine/editor/contributions.py`, `tests/test_editor_render_targets.py`

- [ ] Write failing tests for registration, replacement, removal, unknown-target rejection, callback failure handling, and removal while an intent is pending.
- [ ] Implement an editor-side target map that resolves callbacks but does not schedule, batch, invalidate, or mutate `UICoordinator` state.
- [ ] Add tests proving owner/generation values remain on `RenderIntent` and stale intents cannot reach replacement callbacks.
- [ ] Commit: `feat: add editor render target registry`.

### Task 5: Add feature lifecycle and panel seam

**Files:** `src/expra_engine/editor/contributions.py`, `tests/test_editor_contributions.py`

- [ ] Write failing tests for idempotent `start()`/`stop()`, start-failure rollback, stop-failure isolation, feature removal, and optional panel contribution metadata.
- [ ] Implement lifecycle ownership in the registry; never let a feature own the Tk root or coordinator shutdown.
- [ ] Commit: `feat: add contribution lifecycle ownership`.

### Task 6: Record the edge-case audit

**Files:** `docs/audits/2026-09-20-editor-contribution-edge-cases.md`

- [ ] Document observed test evidence from the available archives: PPB cleanup, timeout, missing-resource, executor shutdown, and repeated lifecycle cases; reference Expra coalescing, stale, conflict, dead-widget, unsubscribe, and idempotent shutdown cases; Ursina's limited relevant coverage.
- [ ] Map each evidence item to a concrete Expra test name or test group; distinguish adopted cases from intentionally unsupported behavior.
- [ ] Run `git diff --check` and commit: `docs: record editor contribution edge cases`.

## Phase 3: Composition Integration

### Task 7: Create explicit built-in providers

**Files:** `src/expra_engine/editor/contributions.py`, `src/expra_engine/ui/editor_window.py`, `tests/test_editor_contributions.py`

- [ ] Write failing tests for explicit provider ordering and stable IDs for runtime, scene, entity, history, and export groups.
- [ ] Add provider classes/functions that wrap existing `EditorWindow` callbacks through `EditorContext`; do not move business logic into metadata or factories.
- [ ] Keep specialized callbacks direct where contribution metadata would obscure behavior.
- [ ] Commit: `feat: define built-in editor contribution providers`.

### Task 8: Integrate registry without migrating behavior

**Files:** `src/expra_engine/ui/editor_window.py`, `tests/test_editor_ui.py`, `tests/test_editor_contributions.py`

- [ ] Write a composition test proving legacy direct actions still dispatch and the registry can coexist with them without duplicate registration.
- [ ] Construct context, registry, and explicit provider list in `EditorWindow`; register only non-conflicting migrated surfaces first.
- [ ] Preserve all existing action IDs and direct `ButtonCoordinator` semantics.
- [ ] Commit: `feat: integrate opt-in editor contribution registry`.

### Task 9: Migrate menus, toolbar, and shortcuts incrementally

**Files:** `src/expra_engine/ui/editor_window.py`, `src/expra_engine/ui/toolbar.py`, `src/expra_engine/ui/styles.py`, tests for the affected surfaces

- [ ] Add failing regression tests for Play/Pause/Stop state, New Scene, Save, Undo, Redo, Export, menu invocation, toolbar invocation, and Ctrl-Z/Ctrl-Y.
- [ ] Migrate runtime, scene, entity, history, and export contributions one group at a time; after each group run its focused tests.
- [ ] Map semantic style roles to current styles and verify the visual roles are unchanged.
- [ ] Remove only duplicated manual wiring made redundant by a migrated contribution; leave specialized wiring intact.
- [ ] Commit each bounded migration with a `feat:` message.

### Task 10: Replace editor render branching

**Files:** `src/expra_engine/ui/editor_window.py`, `tests/test_editor_render_targets.py`, `tests/test_editor_ui.py`

- [ ] Write failing integration tests for hierarchy, inspector, viewport, and toolbar target callbacks through the registry.
- [ ] Register current targets explicitly, including inspector owner/generation handling, then pass the registry adapter to `UICoordinator.request()`.
- [ ] Remove only the feature-specific `_apply_render()` `elif` chain; do not alter `UICoordinator` scheduling or stale-result logic.
- [ ] Commit: `refactor: route editor renders through target registry`.

### Task 11: Wire lifecycle shutdown safely

**Files:** `src/expra_engine/ui/editor_window.py`, `tests/test_editor_ui.py`, `tests/test_editor_contributions.py`

- [ ] Write failing shutdown tests proving feature stop happens once before delivery/coordinator/root teardown and a feature stop failure does not strand later cleanup.
- [ ] Invoke registry stop/unregister in the existing close path with idempotent guards.
- [ ] Run focused real-Tk tests when a display is available; otherwise run the test doubles and record the environment limitation.
- [ ] Commit: `fix: make editor feature shutdown deterministic`.

## Phase 4: Final Verification

### Task 12: Run static and behavioral validation

**Files:** no source changes unless validation exposes a regression

- [ ] Run `.venv/bin/ruff format src/ tests/`.
- [ ] Run `.venv/bin/ruff check src/ tests/`.
- [ ] Run `.venv/bin/python -m pytest tests/ --tb=short -q`.
- [ ] Run configured mypy and pyright commands from `pyproject.toml` or repository scripts; if unavailable, record the exact command/result.
- [ ] Run `git diff --check`.
- [ ] Run real-Tk editor smoke checks for Play, Pause, Stop, New Scene, Save, Undo, Redo, Export, shortcuts, and shutdown when possible.
- [ ] Review `git diff`, `git status`, and all commits included in the change; ensure unrelated export/UI work remains untouched.
- [ ] Commit any narrowly scoped fixes with the relevant `fix:` or `test:` prefix.

### Task 13: Build the final report

**Files:** final response; update `docs/audits/2026-09-20-editor-contribution-edge-cases.md` only if validation adds evidence

- [ ] Report base commit, compatibility guarantees, unchanged coordinator semantics, preserved action IDs, new architecture, migrated features, smallest new-feature example, regression status, real-Tk status, and exact quality-command results.
- [ ] Choose the final statement only after evidence: `EXPRA EDITOR WIRING IS DECLARATIVE AND BACKWARDS COMPATIBLE` or `FOLLOW-UP REQUIRED — EDITOR STILL REQUIRES CENTRAL MANUAL WIRING`.
