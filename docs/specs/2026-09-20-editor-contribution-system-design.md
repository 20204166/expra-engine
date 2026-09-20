# Expra Editor Contribution System

**Status:** Approved design specification

## Goal

Make new editor capabilities declarative and incrementally adoptable without
replacing `ButtonCoordinator`, changing `UICoordinator` semantics, or forcing
a rewrite of existing editor wiring.

## Constraints

- `ButtonCoordinator` remains the execution and widget-state owner.
- `UICoordinator` remains the batching, visibility, priority, generation,
  owner, stale-result, and render-failure owner.
- Existing coordinator APIs and action IDs remain valid.
- Existing direct wiring remains supported during migration.
- Built-in features are registered through an explicit list, not import or
  filesystem scanning.
- No service locator, event bus, decorator registration, metaclass, or plugin
  discovery framework is introduced.
- No visual redesign is included.

## Architecture

The opt-in contribution layer lives in one standalone module:
`src/expra_engine/editor/contributions.py`.

It provides small dataclasses/protocols for:

- `EditorContext`: explicit typed dependencies for feature callbacks.
- `EditorActionSpec`: stable action ID, callback, initial enabled state, and
  optional enablement policy.
- `MenuContribution`: parent menu, label, action ID, group, order, separator,
  and accelerator metadata.
- `ToolbarContribution`: action ID, label, group, order, and semantic style
  role.
- `ShortcutContribution`: normalized key sequence and action ID.
- `EditorFeature`: an explicit provider contract for contributions and optional
  lifecycle/render/panel seams.
- `ContributionRegistry`: validation, ownership, registration, and cleanup.
- `RenderTargetRegistry`: editor-side target-to-callback resolution.

The registry is additive. Legacy code may continue to call
`ButtonCoordinator.register()`, `.bind()`, `.command()`, `.dispatch()`,
`.set_enabled()`, `.unregister()`, and `.clear_prefix()` directly. Migrated or
new features use the registry; both paths remain valid simultaneously.

## Action Flow

```text
feature declaration
    -> ContributionRegistry validation
    -> ButtonCoordinator.register()
    -> menu/toolbar/shortcut factories
    -> ButtonCoordinator.dispatch(action_id)
    -> feature callback through EditorContext
```

The registry never executes business logic and never bypasses the coordinator.
Disabled actions are rejected consistently from buttons, menus, and shortcuts.

## UI Coordinator Boundary

`UICoordinator` is not extended with feature-specific registration. Its public
semantics and safety checks remain unchanged.

`RenderTargetRegistry` is an editor-side adapter used by the composition root:

```text
UICoordinator.request(RenderIntent, render_target_registry.apply)
                                             |
                                             +-- target ID -> callback
```

The registry maps targets such as `hierarchy`, `inspector`, `viewport`, and
`toolbar` to callbacks. It supports explicit registration, replacement, and
removal. An unknown target is rejected before queuing a render intent and does
not invoke a callback; this is a registry validation result, not a change to
`UICoordinator` behavior.

Generation, owner, invalidation, visibility, batching, priority, stale-result
rejection, and callback-failure isolation remain in `UICoordinator`. Removing
or replacing a target cannot allow a queued stale intent to reach a new owner.

## Styles

Contribution metadata refers to semantic style roles, not raw Tk style names.
The toolbar factory maps roles to existing definitions in `ui/styles.py`:

- `play` uses the existing play style.
- `stop` uses the existing stop style.
- `neutral` covers pause, scene, save, and export controls.

Features cannot mutate global Tk styling through contribution metadata. A new
role requires an explicit addition to `styles.py` and a factory mapping. The
current Play/Pause/Stop appearance and grouping remain equivalent.

## Registration and Lifecycle

The composition root owns one registry and one explicit built-in provider list.
Registration is transactional from the caller's perspective: validate all
action IDs, shortcuts, menu references, style roles, and owned targets before
mutating coordinator state.

Feature ownership records all installed actions, shortcuts, widgets, render
targets, and lifecycle hooks. Unregister is idempotent and removes only owned
state. `start()` and `stop()` are optional, explicit, idempotent, and owned by
the editor; feature failures cannot strand callbacks or own the Tk root.

External plugin discovery is deferred. The provider contract must not prevent
future package-entry-point adapters, but no loader is implemented now.

## Incremental Migration

1. Add the contribution model, registry, render-target registry, factories,
   and compatibility tests without changing current behavior.
2. Migrate runtime controls, scene, entity, history, and export one group at a
   time, preserving IDs: `play`, `pause`, `stop`, `new_scene`, `save_scene`,
   `add_entity`, `delete_entity`, `undo`, `redo`, and `editor.export_game`.
3. Replace only the editor's `_apply_render()` branching with registered
   targets after registry tests are green.
4. Retain direct wiring for specialized controls where a contribution would be
   less clear.
5. Add lifecycle shutdown before delivery queues, coordinators, or the Tk root
   are destroyed.

## Edge-Case Audit Matrix

The test design is informed by the available Ursina, PursuedPyBear, and
reference Expra test suites. Production implementations are not copied.

| Area | Required cases |
| --- | --- |
| Registration | duplicate IDs, duplicate normalized shortcuts, empty contributions, invalid menu/style references, all-or-nothing registration |
| Compatibility | direct coordinator registration, binding, dispatch, enablement, prefix cleanup, dead widgets |
| Unregister | repeated unregister, owned-state cleanup, removal after partial setup, no removal of another feature's state |
| Lifecycle | repeated start/stop, start failure rollback, stop failure isolation, shutdown before root destruction |
| Shortcuts | normalization, disabled actions, unknown actions, duplicate conflicts, latest callback not silently winning |
| UI surfaces | one callback invoked once through menu, toolbar, and shortcut; equivalent disabled behavior |
| Render targets | registration, replacement, removal, unknown target, callback exception, pending intent during removal/replacement |
| Render safety | generation, owner, invalidation, stale rejection, visibility, batching, priority, coalescing preserved |
| Cleanup | fresh registry per test, global/shared state reset, executor/queue shutdown, idempotent shutdown |
| Styles | existing role mapping, missing role rejection, semantic role fallback only where explicitly defined |

Reference findings: Ursina's available archive has no substantial contribution
or editor edge-case suite; PPB emphasizes isolated global state, missing
resources, timeout, cleanup, executor shutdown, and repeated lifecycle; the
reference Expra tests emphasize coalescing, stale results, idempotent shutdown,
unknown handlers, duplicate registration, dead widgets, and unsubscribe.

## Testing

Add focused tests before each implementation slice:

- `tests/test_editor_contributions.py` for metadata, registry ownership,
  conflicts, transactional setup, lifecycle, and legacy compatibility.
- `tests/test_editor_render_targets.py` for target resolution, replacement,
  removal, unknown targets, callback failures, and owner/generation safety.
- Factory tests for menu, toolbar, shortcut, and semantic style behavior.
- Existing `ButtonCoordinator` and `UICoordinator` tests remain unchanged where
  possible and continue to pass.
- Real-Tk tests verify Play, Pause, Stop, New Scene, Save, Undo, Redo, Export,
  shortcut dispatch, and shutdown when a display is available.

Validation includes the full test suite, focused coordinator/contribution
tests, Ruff, mypy, pyright, `git diff --check`, and a wheel/build check where
applicable.

## Non-Goals

- Replacing either coordinator.
- Rewriting the editor in one pass.
- Automatic filesystem or import scanning.
- Arbitrary plugin loading.
- A docking framework.
- A new styling system.
- Moving feature business logic into menu, toolbar, or render factories.
