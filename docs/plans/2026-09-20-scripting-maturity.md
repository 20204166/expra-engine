# Expra Scripting Maturity Implementation Plan

> **For agentic workers:** Implement task-by-task with a red-green test cycle.

**Goal:** Mature Expra gameplay scripting from explicit runtime instances into
a safe, resource-backed, editor/export-integrated Behaviour system with a
simple public API.

**Architecture:** `ScriptComponent` stores data only. `ScriptRegistry` resolves
validated project ResourceIds with normal import machinery. One
`BehaviourSystem` owns live instances and uses the existing Engine, RuntimeClock,
EventQueue, InputMap, scene stack, resource filesystem, CommandStack, and
exporter. No second loop, queue, global state, or serialized executable data.

**Test strategy:** Every new behavior starts with a focused failing test. The
matrix-derived failure cases from Ursina, PPB, and MiniPyEngine are grouped by
owner below. The final end-to-end test exercises project script file -> scene
component -> registry/import -> runtime lifecycle -> semantic input and
Transform mutation -> exposed values -> stop/restore -> export manifest ->
transactional reload failure.

**Compatibility invariant:** scripting is additive. An entity without a
`ScriptComponent` uses the existing Expra path unchanged. A script with no
handler for an operation passes through to the default owner. Explicit script
override results suppress only the conflicting customizable operation; scripts
never replace Engine, Scene, RuntimeClock, EventQueue, physics, resource, or
serialization ownership. Legacy/default and scripted Neon Arena-style paths
are both regression-tested.

---

## Task 1: Public Behaviour Contract

**Files:** `runtime/behaviour.py`, `runtime/context.py`, `runtime/input.py`,
`core/entity.py`, `tests/test_scripting_foundation.py`.

- Add `exposed(default, *, min, max, step, tooltip, category, readonly, choices)`
  with deterministic inheritance and validated assignment. Reject bool-as-int,
  non-finite floats, wrong enums, unsupported values, and partial mutation.
- Add explicit context binding and thin helpers: `get_component`,
  `require_component`, `has_component`, `input`, `engine`, `scene`, `emit`.
- Make `on_update(dt)` and `on_fixed_update(dt)` the public hooks while
  preserving the existing event/signal callback compatibility adapter.
- Add enabled transition hooks exactly once and destroy-once state.
- Tests: public Player example, missing/disabled/removed components, inherited
  fields, invalid values, entity/script enabled combinations, fixed timing,
  pause/resume/time scale, and no giant resume spike.

## Task 2: Serialized ScriptComponent

**Files:** `core/component.py`, `core/entity.py`, `core/scene.py`,
`filesystem/ids.py`, `tests/test_scripting_serialization.py`.

- Add `project://` ResourceIds with traversal, absolute path, separator, drive,
  NUL, and normalization rejection.
- Add `ScriptComponent(script_id, behaviour_class, enabled, exposed_values,
  order)` to the component registry. Preserve unknown script metadata rather
  than deleting scene data.
- Serialize only identity/configuration. Never serialize live instances,
  modules, callbacks, services, closures, or timeline handles.
- Tests: deep JSON round-trip, missing script/class, added/removed/renamed/type
  changed/default changed/removed enum exposed fields, multiple components and
  deterministic order.

## Task 3: ScriptRegistry and BehaviourSystem

**Files:** `runtime/script_registry.py`, `runtime/behaviour_system.py`,
`core/engine.py`, `runtime/events.py`, `tests/test_behaviour_system.py`.

- Resolve only normalized project script ResourceIds under the project root;
  reject absolute paths, `../`, symlink escapes, arbitrary module names, and
  non-Python resources. Load with `importlib` machinery, never source `exec`.
- Validate missing module, syntax/import failure, missing class, wrong base,
  duplicate identity, circular import, and structured error context.
- Make the single system instantiate one fresh Behaviour per ScriptComponent,
  attach context, dispatch update/fixed/event/input, and destroy exactly once.
- Use stable snapshots/deferred mutation for self/other destruction, disable,
  add/remove behaviour/entity, scene transitions, Quit, and nested signals.
- Startup is atomic: failed construction/start tears down earlier instances and
  leaves edit state unchanged. Callback policy is explicit, logged with script
  ID/class/entity/callback, and tested for every lifecycle callback.
- Tests include Ursina enabled/disabled/ancestor filtering, PPB handler
  validation/deferred events/scene flush, MiniPyEngine live-list removal cases,
  ordering, reentrancy, partial-start failure, repeated Play/Stop, and memory
  retention smoke checks.
- Add default-only, unrelated-script extension, handled override,
  script-disable/remove fallback, and script-load-failure fallback tests. A
  broken optional script must not disable unrelated default engine behavior.

## Task 4: Existing Runtime Services

**Files:** `runtime/context.py`, `runtime/timeline.py`, `runtime/tween.py`,
`runtime/sequence.py`, `runtime/invoke.py`, `runtime/physics.py`, tests.

- Expose existing clock/input/events/timeline services through context without
  creating script schedulers or worker callbacks.
- Cancel entity-owned delayed work when behaviour/entity/scene is destroyed.
- Route supported physics/collision events through EventQueue only; do not invent
  unsupported physics capabilities.
- Tests: callback after destroy, destroy during tween/sequence, scene transition,
  collision partner destruction, duplicate enter/exit policy, runtime-thread
  callback boundary, and no duplicate subscriptions after Play/Stop/Play.

## Task 5: Script Resource and Safe Reload

**Files:** `runtime/script_registry.py`, `runtime/hot_reload.py`, tests.

- Track ResourceId -> module key -> generation and reuse modules for instances.
- Stage changed-module import and class validation before touching live state.
- Transfer only compatible exposed values; do not migrate arbitrary private
  runtime state. Latest generation wins; stale completions are ignored.
- On syntax error, ImportError, missing/renamed class/base, dependency failure,
  rapid saves, pause, scene transition, Stop, or destroyed entity, preserve the
  known-good instance and report a chained structured error.
- Tests cover all extracted Ursina hot-reload failures: no `exec`, no scene
  destruction before success, no paused-state leak, no duplicate callbacks,
  old module cleanup, dependency changes, circular imports, and unrelated
  scripts unaffected.

## Task 6: Inspector, Commands, and Script Creation

**Files:** `editor/script_commands.py`, `editor/contributions.py`,
`ui/inspector.py`, `ui/editor_window.py`, tests.

- Add generic exposed-property rows from metadata; do not add per-script fields
  to InspectorPanel or coordinator internals.
- Add attach/remove/create actions through declarative contributions. Generated
  templates use the real public API and never overwrite existing files.
- Commands identify entity and scene by stable IDs and no-op safely if deleted
  or selection changes. Invalid edits create no command; redo branches clear.
- Tests: valid/invalid identifiers, reserved words, duplicate/existing files,
  path traversal/root escape, attach missing/bad class/duplicate/multiple,
  stale selection, delete-before-undo, property undo/redo, and inspector
  rendering without a display where possible.

## Task 7: Export and Runtime Boundary

**Files:** `export/exporter.py`, `export/manifest.py`, `export/verify.py`,
`runtime/__init__.py`, tests.

- Include registered project script resources and dependencies in source and
  bytecode builds; fail clearly on compile/import/dependency errors.
- Ensure packaged registry resolves the same logical IDs without editor/Tk.
- Verify exported runtime contains no `tkinter`, `ttk`, editor, coordinator,
  or delivery-queue imports and cannot use serialized arbitrary imports.
- Tests: source, bytecode, nested packages, relative helper import, missing
  dependency, path portability, manifest inclusion, and clean-install import.

## Task 8: Dogfood and End-to-End Regression

**Files:** `examples/player_behaviour.py`, `tests/test_scripting_end_to_end.py`,
`docs/SCRIPTING.md`, architecture/integration maps.

- Add a minimal PlayerBehaviour with speed/health, semantic movement, transform
  mutation, one event, one existing tween/timeline operation, and clean stop.
- End-to-end test creates a temporary project script, serializes a scene,
  loads/validates it, runs input/update, checks exposed mutation and lifecycle,
  exports source/bytecode manifest, and proves failed reload leaves old behavior.
- Preserve a legacy/default Neon Arena-style fixture and run it both without a
  script and with a script that calls existing engine services; compare default
  movement/collision/animation ownership and prove no duplicate movement.

## Task 9: Quality Gates

- Run focused scripting tests, full pytest, `ruff check .`, `ruff format --check .`,
  `pyright`, `mypy --ignore-missing-imports src tests`, and `git diff --check`.
- Run wheel/export verification and report unavailable GUI/Windows checks
  honestly. Review all changed ownership for duplicate registries/schedulers.
- Update the parity matrix with final A/B/C/D/E counts and exact test references.
