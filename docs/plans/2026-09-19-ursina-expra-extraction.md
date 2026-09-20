# Ursina to Expra Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit Ursina 8.2.0 and add a tested, backend-neutral foundation for Expra game UI and 2D runtime without replacing existing Expra systems.

**Architecture:** Preserve Expra's Entity/Component, Engine/EventQueue/RuntimeClock/RuntimeSystem, coordinator, editor Tk, and release owners. Add only narrowly owned pure data/geometry/runtime modules after repository-wide ownership searches. Renderer and platform adapters remain explicit future seams; game runtime never imports Tk.

**Tech Stack:** Python 3.12, dataclasses, `unittest`, Tk only for editor integration tests, Ruff, Pyright, mypy, existing wheel scripts, supplied Ursina source at `/home/btn17/Downloads/ursina-master`.

---

## File Structure Map

### Documentation

- Create `docs/URSINA_INTEGRATION_MAP.md`: complete source-by-source A-E audit,
  ownership decisions, risks, test matrix, rejected patterns, and provenance.
- Modify `docs/GAME_UI_FUTURE.md`: record the approved renderer-neutral model,
  safe-area contract, runtime/editor boundary, and implementation status.
- Modify `docs/GAME_EXPORT_FUTURE.md`: record exporter concepts and retain the
  existing wheel/release owner.
- Modify `THIRD_PARTY_NOTICES.md` only if substantial Ursina implementation is
  adapted; preserve MIT attribution exactly.

### Renderer-neutral UI

- Create `src/expra_engine/ui_model/geometry.py`: immutable logical sizes,
  anchors, pivots, offsets, safe areas, reference-resolution scaling, and
  resolved rectangles.
- Create `src/expra_engine/ui_model/nine_slice.py`: validated nine-slice data
  and renderer-neutral patch geometry.
- Create `src/expra_engine/ui_model/controls.py`: button, toggle, slider,
  selection group, and progress state machines with no GUI imports.
- Create `src/expra_engine/ui_model/focus.py`: focus order and semantic focus
  traversal contracts.
- Create `tests/test_ui_model_geometry.py`, `tests/test_ui_model_nine_slice.py`,
  `tests/test_ui_model_controls.py`, and `tests/test_ui_model_focus.py`.

### Runtime interaction and timing

- Create `src/expra_engine/runtime/input.py`: instance-scoped physical-input,
  binding, action, held-state, and rebinding model.
- Create `src/expra_engine/runtime/pointer.py`: backend-neutral pointer,
  capture, hover, click, drag, and focus event contracts.
- Modify `src/expra_engine/runtime/events.py` only for compatible typed event
  additions; do not replace existing event names or queue behavior.
- Create `src/expra_engine/runtime/timeline.py`: deterministic sequence/tween
  runtime system driven by existing update events with scaled/unscaled time.
- Modify `src/expra_engine/runtime/clock.py` only after tests prove the smallest
  pause/unscaled extension is required.
- Create `tests/test_runtime_input.py`, `tests/test_runtime_pointer.py`, and
  `tests/test_runtime_timeline.py`.

### 2D runtime

- Create `src/expra_engine/runtime/animation.py`: immutable clips, frame
  durations, sprite-sheet regions, looping, and named state control.
- Create `src/expra_engine/runtime/follow.py`: validated exponential follow
  behavior using existing 2D values.
- Create `src/expra_engine/runtime/tilemap.py`: grid data, tile layers,
  neighbor masks, deterministic variation, and renderer-neutral autotile rules.
- Create tests under `tests/test_runtime_animation.py`,
  `tests/test_runtime_follow.py`, and `tests/test_runtime_tilemap.py`.

### Editor and future contracts

- Create `src/expra_engine/editor/safe_expression.py`: strict numeric parser
  for the VecField use case; no `eval`, calls, names, attributes, or indexing.
- Extend `src/expra_engine/ui/inspector.py` only after parser tests pass.
- Create `src/expra_engine/editor/assets.py`: scan request/result contracts;
  actual work must use existing `AppCoordinator` and delivery queue.
- Create `src/expra_engine/runtime/dialogue.py`: typed dialogue graph and
  explicit conditions/actions, without executable content.
- Create `tests/test_safe_expression.py`, `tests/test_runtime_dialogue.py`, and
  `tests/test_editor_assets.py`; retain existing editor ownership.

### Validation and release

- Modify `tests/test_release.py` only for additive export-contract coverage.
- Run configured Ruff, Pyright, mypy, all unittest discovery, package build,
  wheel verification, `git diff --check`, and real-Tk smoke tests where needed.

---

## Task 1: Complete the Audit Map

**Files:** Create `docs/URSINA_INTEGRATION_MAP.md`; modify
`docs/GAME_UI_FUTURE.md` and `docs/GAME_EXPORT_FUTURE.md`; inspect but do not
modify `/home/btn17/Downloads/ursina-master`.

- [ ] **Step 1: Write the failing documentation checks**

Add a small `tests/test_ursina_integration_map.py` test that asserts the map
contains the Ursina version/license, all required source families, the exact
final safety answers, and the three hard constraints: no replaced Expra
systems, no Panda dependency, and no Tk game-runtime dependency.

- [ ] **Step 2: Run the documentation test**

Run:

```bash
.venv/bin/python -m unittest tests.test_ursina_integration_map -v
```

Expected result before the map exists: failure because the documentation file
does not exist.

- [ ] **Step 3: Write the integration map**

For every required source, record classification, semantics, coupling removed,
Expra owner, tests, deferred behavior, and rejection reason. Include explicit
rows for `button.py`, `nine_slice.py`, `text_field.py`, `input_handler.py`,
`mouse.py`, `window.py`, `tilemap.py`, `build.py`, `vec_field.py`,
`file_browser.py`, `color_picker.py`, `gradient_editor.py`, `conversation.py`,
and `hot_reloader.py`, plus every requested neighboring prefab/script.

- [ ] **Step 4: Run the documentation test**

Run the same unittest command. Expected result: PASS.

- [ ] **Step 5: Commit the audit map**

```bash
git add docs/URSINA_INTEGRATION_MAP.md docs/GAME_UI_FUTURE.md docs/GAME_EXPORT_FUTURE.md tests/test_ursina_integration_map.py
git commit -m "docs: map Ursina semantics to Expra owners"
```

---

## Task 2: Add Renderer-Neutral Layout Geometry

**Files:** Create `src/expra_engine/ui_model/geometry.py` and
`tests/test_ui_model_geometry.py`.

- [ ] **Step 1: Write failing tests**

Cover normalized anchors, pivot, offsets, fixed and stretched dimensions,
minimum/maximum size, reference-resolution scaling, arbitrary aspect ratios,
DPI scale, and safe-area insets. Assert invalid negative sizes and inverted
safe areas raise `ValueError`.

- [ ] **Step 2: Run the focused tests and confirm the expected import failure**

```bash
.venv/bin/python -m unittest tests.test_ui_model_geometry -v
```

- [ ] **Step 3: Implement the smallest immutable geometry model**

Use frozen dataclasses and explicit tuples. Resolve a `RectTransform` against a
parent rectangle and safe-area rectangle; do not import Tk, Ursina, Panda, or
design adapters. Keep `RectTransform` layout intent separate from renderer
pixels.

- [ ] **Step 4: Run focused, type, and lint checks**

```bash
.venv/bin/python -m unittest tests.test_ui_model_geometry -v
.venv/bin/ruff check src tests
.venv/bin/pyright
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/ui_model tests/test_ui_model_geometry.py
git commit -m "feat: add renderer-neutral UI rectangle model"
```

---

## Task 3: Add Nine-Slice Geometry

**Files:** Create `src/expra_engine/ui_model/nine_slice.py` and
`tests/test_ui_model_nine_slice.py`.

- [ ] **Step 1: Write failing tests**

Test tiny, wide, tall, square, and aspect-ratio-changing panels; fixed corners;
stretched borders/center; optional outset/padding; zero/negative dimensions;
and borders larger than half the panel dimension.

- [ ] **Step 2: Run focused tests and verify the missing-module failure**

```bash
.venv/bin/python -m unittest tests.test_ui_model_nine_slice -v
```

- [ ] **Step 3: Implement validated renderer-neutral patch data**

Return nine named rectangles or equivalent immutable patch records in logical
coordinates. Clamp oversized borders to the available dimension without
negative rectangles. Do not create Panda meshes or texture objects.

- [ ] **Step 4: Run focused tests and static checks**

```bash
.venv/bin/python -m unittest tests.test_ui_model_nine_slice -v
.venv/bin/ruff check src tests
.venv/bin/pyright
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/ui_model/nine_slice.py tests/test_ui_model_nine_slice.py
git commit -m "feat: add renderer-neutral nine-slice geometry"
```

---

## Task 4: Add Pure UI Control State

**Files:** Create `src/expra_engine/ui_model/controls.py` and
`tests/test_ui_model_controls.py`.

- [ ] **Step 1: Write failing tests**

Cover button normal/hover/pressed/disabled/selected states; toggle changes;
slider min/max/step/clamp/live-change/commit; selection-group minimum and
maximum selection; and progress-bar clamp, text, and segmented metadata.

- [ ] **Step 2: Run tests and confirm missing implementation**

```bash
.venv/bin/python -m unittest tests.test_ui_model_controls -v
```

- [ ] **Step 3: Implement explicit state transitions**

Use typed dataclasses and return state-change records rather than invoking Tk
callbacks. Reject invalid ranges and impossible selection constraints. Keep
health/mana/xp meanings outside the generic progress model.

- [ ] **Step 4: Run focused tests and static checks**

```bash
.venv/bin/python -m unittest tests.test_ui_model_controls -v
.venv/bin/ruff check src tests
.venv/bin/pyright
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/ui_model/controls.py tests/test_ui_model_controls.py
git commit -m "feat: add backend-neutral game UI control state"
```

---

## Task 5: Add Focus and Pointer Contracts

**Files:** Create `src/expra_engine/ui_model/focus.py`,
`src/expra_engine/runtime/pointer.py`, and tests for both.

- [ ] **Step 1: Write failing tests**

Test deterministic next/previous focus, disabled/skipped controls, wrap policy,
pointer enter/leave, press/release, capture, drag/drop, double-click timing,
release outside bounds, and focus loss clearing held/captured state.

- [ ] **Step 2: Run the focused tests and confirm missing imports**

```bash
.venv/bin/python -m unittest tests.test_ui_model_focus tests.test_runtime_pointer -v
```

- [ ] **Step 3: Implement instance-scoped contracts**

Represent events as immutable records and keep capture/focus ownership explicit.
Do not inspect global mouse state, create colliders, or depend on a renderer.

- [ ] **Step 4: Run focused tests, then commit**

```bash
.venv/bin/python -m unittest tests.test_ui_model_focus tests.test_runtime_pointer -v
git add src/expra_engine/ui_model/focus.py src/expra_engine/runtime/pointer.py tests/test_ui_model_focus.py tests/test_runtime_pointer.py
git commit -m "feat: define runtime focus and pointer contracts"
```

---

## Task 6: Add Action Maps and Rebinding

**Files:** Create `src/expra_engine/runtime/input.py` and
`tests/test_runtime_input.py`; modify `src/expra_engine/runtime/events.py` only
if an existing event shape is insufficient.

- [ ] **Step 1: Write failing tests**

Test physical-to-semantic action resolution, press/release/held state,
modifier combinations, rebinding collision policy, unbind of absent bindings,
focus-loss reset, keyboard/mouse/controller/touch-neutral identifiers, and
independent input instances.

- [ ] **Step 2: Run focused tests and verify missing module failure**

```bash
.venv/bin/python -m unittest tests.test_runtime_input -v
```

- [ ] **Step 3: Implement the instance-scoped action map**

Use immutable binding identifiers and explicit action events. Preserve the
physical-input to action-map to semantic-action boundary. Do not hardcode W,
Space, or mouse buttons in gameplay APIs.

- [ ] **Step 4: Run focused tests and static checks**

```bash
.venv/bin/python -m unittest tests.test_runtime_input -v
.venv/bin/ruff check src tests
.venv/bin/pyright
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/runtime/input.py src/expra_engine/runtime/events.py tests/test_runtime_input.py
git commit -m "feat: add backend-neutral runtime action maps"
```

---

## Task 7: Add Deterministic Runtime Timeline

**Files:** Create `src/expra_engine/runtime/timeline.py` and
`tests/test_runtime_timeline.py`; modify `runtime/system.py` only if the
existing lifecycle seam cannot host the system.

- [ ] **Step 1: Write failing tests**

Cover delay, interpolation, callback ordering, pause/resume, cancellation,
looping under large deltas, zero duration, scaled/unscaled time, and stop
cleanup. Assert the system consumes existing update events rather than making
a second timing loop.

- [ ] **Step 2: Run focused tests and verify missing implementation**

```bash
.venv/bin/python -m unittest tests.test_runtime_timeline -v
```

- [ ] **Step 3: Implement a RuntimeSystem-backed timeline**

Use explicit timeline ownership and injected callbacks. Drive progress from
`RuntimeClock`/`Update`; do not reuse `PendingTransition` or global Ursina
sequence state. Handle large deltas with deterministic catch-up and bounded
zero-duration behavior.

- [ ] **Step 4: Run runtime integration and existing timing tests**

```bash
.venv/bin/python -m unittest tests.test_runtime_timeline tests.test_runtime_clock tests.test_engine_runtime -v
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/runtime/timeline.py tests/test_runtime_timeline.py
git commit -m "feat: add deterministic runtime timelines"
```

---

## Task 8: Add Sprite and Animation Contracts

**Files:** Create `src/expra_engine/runtime/animation.py` and
`tests/test_runtime_animation.py`.

- [ ] **Step 1: Write failing tests**

Test sprite metadata for texture identity, pixels-per-unit, and aspect policy;
frame-duration validation; sprite-sheet region calculation; loop and
play/pause/resume; and named animator state transitions including invalid state
and missing clip cases.

- [ ] **Step 2: Run focused tests and verify missing implementation**

```bash
.venv/bin/python -m unittest tests.test_runtime_animation -v
```

- [ ] **Step 3: Implement immutable clips and a runtime state controller**

Keep asset loading out of constructors. Require positive FPS/durations, copy
caller-owned mappings, and expose renderer-facing frame regions as plain data.
Use the timeline/runtime clock seam rather than per-animation global loops.

- [ ] **Step 4: Run focused tests and static checks**

```bash
.venv/bin/python -m unittest tests.test_runtime_animation -v
.venv/bin/ruff check src tests
.venv/bin/pyright
```

- [ ] **Step 5: Commit**

```bash
git add src/expra_engine/runtime/animation.py tests/test_runtime_animation.py
git commit -m "feat: add renderer-neutral sprite animation contracts"
```

---

## Task 9: Add Follow and Tilemap Data

**Files:** Create `src/expra_engine/runtime/follow.py`,
`src/expra_engine/runtime/tilemap.py`, and focused tests.

- [ ] **Step 1: Write failing follow tests**

Test exponential convergence, zero speed, negative speed rejection, large
delta behavior, and no dependency on Ursina vector types.

- [ ] **Step 2: Run follow tests and confirm the missing-module failure**

```bash
.venv/bin/python -m unittest tests.test_runtime_follow -v
```

- [ ] **Step 3: Implement follow behavior and run tests**

Use plain 2D values and a validated nonnegative speed. Run
`.venv/bin/python -m unittest tests.test_runtime_follow -v` and require PASS.

- [ ] **Step 4: Write failing tilemap tests**

Cover empty/one-cell maps, edge/corner neighbor masks, negative/out-of-range
coordinates, stable repeated generation, deterministic variation without
mutating process-global RNG, invalid dimensions, and layer separation.

- [ ] **Step 5: Run tilemap tests and confirm the missing-module failure**

```bash
.venv/bin/python -m unittest tests.test_runtime_tilemap -v
```

- [ ] **Step 6: Implement renderer-neutral tilemap data**

Use explicit bounds checks, seeded local variation, immutable tile coordinates,
and separate tile data from rendering/collision. Do not write files, print per
tile, or import Panda.

- [ ] **Step 7: Run focused tests and commit**

```bash
.venv/bin/python -m unittest tests.test_runtime_follow tests.test_runtime_tilemap -v
git add src/expra_engine/runtime/follow.py src/expra_engine/runtime/tilemap.py tests/test_runtime_follow.py tests/test_runtime_tilemap.py
git commit -m "feat: add 2D follow and tilemap data contracts"
```

---

## Task 10: Add Typed Dialogue and Safe Numeric Editing

**Files:** Create `src/expra_engine/runtime/dialogue.py`,
`src/expra_engine/editor/safe_expression.py`, and tests; modify
`src/expra_engine/ui/inspector.py` only for the tested scrub/parse seam.

- [ ] **Step 1: Write failing parser and dialogue tests**

Reject names, calls, attributes, indexing, imports, `eval`/`exec`, NaN/inf,
malformed syntax, and unbounded literals. Test accepted arithmetic `10+5`,
`32/2`, and `-4*3`. Test dialogue typed nodes, choices, conditions,
explicit actions, malformed indentation, missing variables, and branch limits.

- [ ] **Step 2: Run focused tests and verify missing implementation**

```bash
.venv/bin/python -m unittest tests.test_safe_expression tests.test_runtime_dialogue -v
```

- [ ] **Step 3: Implement a restricted AST evaluator and dialogue model**

Allow only numeric constants, unary plus/minus, and arithmetic operators with
explicit depth/size limits. Dialogue content stores typed conditions/actions;
it never executes source text or arbitrary callbacks from serialized data.

- [ ] **Step 4: Add inspector scrubbing after parser tests pass**

Keep mutation behind the existing inspector/action boundary, preserve integer
versus float intent, and cover drag increments, invalid text, and undo-ready
change records without adding a second editor coordinator.

- [ ] **Step 5: Run focused tests and commit**

```bash
.venv/bin/python -m unittest tests.test_safe_expression tests.test_runtime_dialogue tests.test_editor_ui -v
git add src/expra_engine/runtime/dialogue.py src/expra_engine/editor/safe_expression.py src/expra_engine/ui/inspector.py tests/test_safe_expression.py tests/test_runtime_dialogue.py
git commit -m "feat: add safe numeric and dialogue foundations"
```

---

## Task 11: Add Async Asset-Browser Contracts

**Files:** Create `src/expra_engine/editor/assets.py` and tests; extend existing
`AppCoordinator` integration only after inspecting its current seams.

- [ ] **Step 1: Write failing contract tests**

Cover folders-first name sorting, filtering, selection, folder navigation,
path display, open/save mode, overwrite confirmation, cancellation, stale
generation rejection, missing folders, permission errors, and empty results.

- [ ] **Step 2: Run focused tests and verify missing implementation**

```bash
.venv/bin/python -m unittest tests.test_editor_assets -v
```

- [ ] **Step 3: Implement pure result normalization and request contracts**

Keep directory enumeration injectable and off the Tk thread. Route worker
delivery through existing `AppCoordinator` and `TkDeliveryQueue`; do not copy
Ursina synchronous `Path.iterdir()` UI behavior.

- [ ] **Step 4: Run focused coordinator and asset tests, then commit**

```bash
.venv/bin/python -m unittest tests.test_editor_assets tests.test_app_coordinator tests.test_delivery_queue -v
git add src/expra_engine/editor/assets.py tests/test_editor_assets.py
git commit -m "feat: define asynchronous asset browser contracts"
```

---

## Task 12: Document Platform, Export, and Deferred Features

**Files:** Modify `docs/GAME_EXPORT_FUTURE.md`, `docs/GAME_UI_FUTURE.md`,
`docs/ARCHITECTURE.md`, and `THIRD_PARTY_NOTICES.md` only when source-derived
code has been adapted.

- [ ] **Step 1: Write documentation assertions**

Assert the docs explicitly state that Expra’s release tooling remains the
owner; exporter concepts are future references; hot reload uses controlled
asset invalidation rather than `exec`; window/display settings belong behind a
platform backend; and dialogue, color/gradient, radial menu, grid editor,
mobile touch, and renderer implementation remain scoped contracts.

- [ ] **Step 2: Run the documentation tests before editing**

```bash
.venv/bin/python -m unittest tests.test_ursina_integration_map -v
```

- [ ] **Step 3: Update the docs and provenance**

Record exact Expra owners, deferred candidates, security/platform/lifecycle
decisions, and any MIT notice required by adapted substantial source.

- [ ] **Step 4: Run documentation and diff checks**

```bash
.venv/bin/python -m unittest tests.test_ursina_integration_map -v
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md docs/GAME_UI_FUTURE.md docs/GAME_EXPORT_FUTURE.md THIRD_PARTY_NOTICES.md
git commit -m "docs: record Expra runtime platform boundaries"
```

---

## Task 13: Full Validation and Audit Report

**Files:** Modify `docs/URSINA_INTEGRATION_MAP.md` with final validation results;
do not alter unrelated worktree changes.

- [ ] **Step 1: Run all tests**

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass. Existing unrelated failures must be reported with
their exact test names and not hidden.

- [ ] **Step 2: Run static and package checks**

```bash
.venv/bin/ruff check src tests
.venv/bin/pyright
.venv/bin/mypy src tests
git diff --check
./scripts/build-wheel.sh
./scripts/verify-wheel.sh
```

- [ ] **Step 3: Run real-Tk smoke validation where editor files changed**

```bash
xvfb-run -a .venv/bin/python -m unittest tests.test_editor_ui -v
```

- [ ] **Step 4: Search for forbidden patterns**

Search Expra source for imports of Ursina/Panda, `eval`, `exec`, global
`camera.ui`-style ownership, and direct Tk imports in runtime modules. Classify
every remaining match as an existing editor boundary, test fixture, or defect.

- [ ] **Step 5: Complete the final audit report**

The report must list audited areas, HIGH/MEDIUM/LOW candidates, owners reused,
specialized callers retained, redundant code removed, runtime work reduced,
separate responsibilities, security/platform/lifecycle/test-seam decisions,
exact validation output, remaining opportunities, changed files, and worktree
status. Choose the mandated final decision only after the evidence supports it.

- [ ] **Step 6: Commit final documentation**

```bash
git add docs/URSINA_INTEGRATION_MAP.md
git commit -m "docs: finalize Ursina extraction audit"
```
