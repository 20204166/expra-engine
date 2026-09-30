# Cross-owner finding: Level anchor queries

> **Historical audit snapshot.** Findings below describe the working tree at
> the time of review, including an in-progress Tk-to-Qt migration. The current
> editor is Qt-only; use the canonical guide for present architecture.

## Finding

`Level` is an authored/core document model, but its anchor lookup and validation
methods import and inspect `runtime.level_anchor.LevelAnchorComponent`:

- `src/expra_engine/core/scene/level.py:99-136` (`find_anchor`,
  `validate_anchors`, and load-time validation)
- `src/expra_engine/runtime/level_anchor.py:31-85` (component type and
  serialization contract)

Runtime and editor callers rely on these methods, including world authoring,
world policy/streaming, and world transitions. Search results included
`editor/world_authoring.py:116,171-172,441-442`,
`runtime/world_policy.py:284`, `runtime/world_streaming.py:550,843`, and
`runtime/world_transition.py:611`.

## Resolution

`LevelAnchorComponent`, `LevelAnchorKind`, and `LevelAnchorShape` are serializable
authored component data and now have their canonical owner in
`src/expra_engine/core/level_anchor.py`. `runtime/level_anchor.py` re-exports
those names for compatibility and continues to own runtime markers such as
`StreamingAnchorComponent` and `WorldPersistentActorComponent`. `Level` keeps its
typed `find_anchor()` and `validate_anchors()` API and imports the component
from core. Registration continues to use the same component class and serialized
type ID (`level_anchor`). Existing runtime/editor callers therefore require no
migration.

The delegated reviewer confirmed that a runtime/editor-only patch could not
resolve the ownership boundary without duplication; no runtime/editor changes
were needed after choosing the canonical owner. This is a bounded ownership
correction, not a redesign of World/Level semantics.

## Additional cross-owner finding: Script component ownership

Before the ownership correction, `ScriptComponent` was documented as data-only
but defined under `runtime/`, while core authored-model code imported it in
`src/expra_engine/core/component.py` for deserialization and in
`src/expra_engine/core/scene/scene_instance.py` to apply Scene Instance
overrides. Its data contract is a logical `ResourceId`, Behaviour class name,
enabled flag, exposed JSON values, order, and preserved extra fields
(`src/expra_engine/core/script_component.py:15-75`). Runtime Behaviour
execution remains a separate concern in `runtime/behaviour_system.py`.

### Ownership resolution

The serializable configuration and unresolved-data fallback belong in core;
execution/registry behavior remains runtime-owned. The canonical data classes
now live in `core/script_component.py`, with the existing
`runtime.script_component` import path retained as a compatibility re-export.
Core deserialization and Scene Instance override application import the core
owner. Existing editor/runtime importers continue to work through the alias.

### Delegated verification

The delegated reviewer checked the runtime/editor consumer boundary and
confirmed that no runtime/editor caller changes were needed. The MCP suite
passed when rerun: `./.venv/bin/python -m pytest -q` from `tools/expra_mcp/` —
109 passed. The focused Engine activation and Scene Instance tests passed — 21
tests. A complete engine-suite rerun was attempted with
`.venv/bin/python -m pytest -q` from the repository root, but exceeded the
300-second timeout at 37%; therefore the previously reported 2519-test full
suite result is not independently confirmed against the current working tree.
The export dependency-closure test imports both `core.level_anchor` and
`core.script_component` from the staged Pygame runtime. The serialized type ID
`script` and unresolved-script round-trip data remain covered by scripting
foundation tests.

This additional issue was found by searching all `ScriptComponent` imports and
reviewing its definition/callers/tests; it is not a request to move Behaviour
execution into core.

## Core-side validation hardening

`LevelMetadata.__post_init__()` now enforces four finite bounds and positive
width/height. Its `from_dict()` path passes the authored value to that canonical
validator instead of attempting `tuple(bounds)` first. This keeps malformed
scalar input on the same contextual `ValueError` path rather than leaking a
`TypeError` (`core/scene/level.py:31-47,58-66`). Regression coverage in
`tests/test_level.py` reproduced the scalar `TypeError` before the change.
Package manifest `format_version` and resource `size` also require exact `int`
values so booleans cannot exploit Python's `bool`-is-an-`int` relationship
(`filesystem/packages.py:47-83`, tests in `tests/test_resource_packages.py`).

## Packaging/consumer verification

The export bundler maintains an explicit runtime-core file allowlist in
`src/expra_engine/export/exporter.py` (`_RUNTIME_CORE_MODULES`). Both newly
canonical modules (`core/level_anchor.py` and `core/script_component.py`) are
included so exported games can import authored component data. The corresponding
regression is in `tests/test_export_exporter.py`; staged-runtime import and
export verification coverage passed in the focused changed-owner set.

Other currently modified runtime files include physics entity-order pruning
and world-transition pose failure ordering. They are separate in-progress
runtime hardening changes, not additional ownership findings in this handoff.

## Core runtime/Scene Instance failure handling

### Engine activation notification — verified resolved; no new change

`Engine.notify_world_level_activated()` records a lifecycle diagnostic, invokes
deactivation hooks in reverse order for systems already notified, and re-raises
the activation exception (`src/expra_engine/core/engine.py:287-304`). The
runtime streaming owner catches the propagated error and rolls back the partial
Level activation (`src/expra_engine/runtime/world_streaming.py:408-439`).
`tests/test_engine_world.py:test_failed_level_activation_rolls_back_prior_runtime_system_hooks`
and `test_world_activation_hook_failure_never_exposes_a_partial_active_level`
pin this behavior. The prior report that the core hook swallowed the error was
not accurate for the current tree; no engine change was required.

### Scene Instance overrides — fixed

Missing override targets and matched entities without a `ScriptComponent` now
raise contextual `ValueError`s instead of silently continuing. Resolution
validates overrides against the source before clearing previously materialized
children, so invalid edits do not discard the prior resolved subtree
(`src/expra_engine/core/scene/scene_instance.py:131-171,183-220`). The
first-entity-with-a-name rule remains unchanged. Regression tests cover missing
targets, non-script targets, and preservation of existing materialization.

## Other dependency candidates reviewed

No further actionable core/filesystem-to-presentation dependency was found.
Core `Engine` coordinates runtime systems; core component registration lazily
connects runtime component implementations to the single authoring schema
registry; `Project` emits a runtime launcher; and `ResourceService` accepts an
optional generic coordinator for asynchronous reads. These are current,
purposeful integration seams and do not import Tk, ttkbootstrap, or pygame into
core/filesystem. They remain unchanged.

## Whole-surface cross-owner audit — in-progress Tk removal

### Scope and baseline

This addendum audits the current dirty working tree at base SHA
`b03ff951fc11bc1864a6efd25e11c00b19e1ac07`, including the in-progress Tk-to-Qt
editor transition. It covers runtime/input, coordinators, editor/UI, export,
observability imports, and MCP editor/static workers. This is a read-only
architecture audit: no source or test files were changed for this addendum.

### Boundaries verified — KEEP / NO CONSOLIDATION NEEDED

- The GUI shell is owned by `editor/qt/`; `main.py:19-27` lazily imports the Qt
  application. `EditorWindowCore` remains toolkit-free and is composed with the
  Qt `EditorWindow` (`editor/window_core.py:1-10`; `editor/qt/main_window.py:1-7,95`).
- Runtime, coordinators, export and observability contain no GUI-toolkit imports.
  `tests/test_gui_boundaries.py:15-110` checks these layers, the shared editor
  core, and staged export. The Qt editor imports PySide6 under `editor/qt/`; the
  MCP editor worker launches the real `EditorWindow`
  (`tools/expra_mcp/src/expra_dev_mcp/_editor_worker.py:237`).
- `runtime/ui/` and `ui_model/` provide toolkit-independent game UI state/layout;
  they do not import the Qt shell. The editor pixel renderer delegates frame
  drawing to `PygameRenderer`; Qt owns pixel conversion/presentation
  (`editor/viewport_core.py:10-12,218`; `ui/editor_pixel_renderer.py:395-429`;
  `editor/qt/image_bridge.py:21-59`). Retained editor overlays remain distinct
  from the runtime pixel layer.
- Export excludes and blocks GUI packages (`export/manifest.py:24-28`,
  `export/packager.py:61-67`, `export/verify.py:13-17`); the staged runtime
  excludes `editor/` and `ui/` (`tests/test_qt_packaging.py:60-86`).
- Core component registration still lazily imports runtime component classes
  to register their serialized types (`core/component.py:186-197,268-279,430-437,
  510-562`). This is a known schema-registration integration seam, not a GUI
  dependency. Keep its single schema-registry owner; continue making direct core
  consumers of serializable data explicit, as with `ScriptComponent` and
  `LevelAnchorComponent`.

### CROSS-OWNER ISSUE — input focus loss is not wired to the input owner

`InputMap.focus_lost()` releases all held bindings (`runtime/input.py:122-134`)
and has unit coverage (`tests/test_runtime_input.py:217-225`), but repository
search found no caller. `PygameRuntime._poll_events()` handles quit, resize,
keyboard and mouse without a focus-loss branch (`runtime/pygame_runtime.py:219-281`).
The Qt preview key filter forwards only key press/release events
(`editor/qt/main_window.py:77-92`). If focus leaves while a key is held and its
key-up is not delivered, the semantic action may remain held. The canonical
reset belongs to `InputMap`; the missing integration belongs to the Pygame and
Qt event adapters, which should dispatch the resulting release events through
the engine. `PointerTracker.focus_lost()` likewise has no backend caller
(`runtime/pointer.py:131-138`); whether that event stream should be integrated
is a separate decision for its backend owner.

### MEDIUM — ViewportCore's toolkit-neutral abstraction is Tk-shaped

`ViewportCore` calls Tk Canvas methods and event sequences while describing
itself as toolkit-independent (`editor/viewport_core.py:1-12,120-166,218-220`).
`QtCanvas` emulates `create_*`, `coords`, `itemconfig`, `bind`, Tk-style event
objects and keysyms (`editor/qt/canvas.py`). This preserves one viewport
implementation; the shared drawing/event surface is retained. **Resolution
(2026-09-29):** the `winfo_*` geometry methods, `after_idle`, `configure`, and
`focus_set` compatibility surface was removed in the consolidation pass; the
viewport now uses `viewport_size()`/`global_origin()` and `schedule_idle()`. The
remaining Tk-flavored surface is the retained canvas item/bind vocabulary, which
is still exercised by the Qt-canvas API tests.

### LOW — ButtonCoordinator's widget contract remains Tk-shaped

`ButtonCoordinator` previously used duck-typed `config`/`winfo_exists` and caught
`RuntimeError` for invalid/destroyed widgets. **Resolution (2026-09-29):** the
coordinator now declares a semantic `ActionWidget` protocol (`bind_action`,
`set_enabled`, `is_valid`) and `QtActionWidget` implements it. The coordinator
still imports no GUI toolkit and treats a raising adapter as a pruned widget.
The `QtCanvas` `itemconfig` alias and the canvas item vocabulary remain the
editor's intentional compatibility surface for shared viewport code.

### LOW — DialogProvider exposes unused GUI parent parameters

The toolkit-neutral `DialogProvider` methods accept `parent: Any`
(`editor/dialog_provider.py:13-69`), while `QtDialogProvider` already binds and
uses a default parent (`editor/qt/dialogs.py:23-31`). Current workflow/action
callers do not pass the optional per-call parent
(`editor/project_workflow.py`, `editor/world_authoring.py`,
`editor/script_actions.py`). This leaks a frontend object into the abstraction
without a current consumer. Owner: the dialog protocol and its Qt adapter; remove
the parameter only after a compatibility review of external provider
implementations.

### MEDIUM — Migration-era Qt tests retain Tk fallback assumptions

The current manifest requires PySide6 and has no Tk fallback (`pyproject.toml:5-15`);
`main.py` launches the Qt editor. However, `tests/test_qt_packaging.py:39-40`
still requires `ttkbootstrap`, and `tests/test_qt_preflight.py:37,54` still
expects an obsolete `--ui tk` fallback. The Qt input/frontend tests also import
missing legacy fixtures (`tests/test_qt_editor_input.py:11` imports
`tests.support.editor_frontends`; `tests/test_editor_frontend_state_sync.py`
and `tests/test_world_frontend_parity.py` import the absent
`tests.test_editor_frontend_parity`). These are migration test-owner issues;
update the stale expectations and consolidate fixtures around the current Qt
frontend without restoring Tk.

Observed validation on this working tree:

- `pytest -q tests/test_gui_boundaries.py tests/test_qt_packaging.py tests/test_runtime_input.py`:
  41 passed, 1 failed because the old test requires `ttkbootstrap`, absent from
  the current PySide-only dependency list.
- A broader selected Qt group excluding the missing parity modules: 110 passed,
  2 failed because preflight tests still require `--ui tk`.
- Including `test_qt_editor_input.py`, `test_editor_frontend_state_sync.py`, or
  `test_world_frontend_parity.py` currently fails during collection because
  referenced legacy support modules are absent.

### KEEP SEPARATE — backend input and rendering adapters

Pygame and Qt translate distinct native key events into the shared
`PhysicalInput`/`InputMap` contract; keep event acquisition backend-local and
test parity for configured controls. The Qt image bridge and Pygame renderer are
also separate consumers of renderer-neutral `RenderFrame`, not competing render
descriptor owners.
