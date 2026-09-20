# Editor Contribution Edge-Case Audit

## Scope

This audit compares tests from the local Ursina, PursuedPyBear, and reference
Expra archives. It uses test behavior as evidence only; production code and
architecture were not copied.

## Evidence

| Reference | Test evidence | Applied to this design |
| --- | --- | --- |
| PPB | `tests/test_assets.py`: isolated global state, missing resources, timeout, cleanup/free, executor shutdown, chained work | Fresh registry state, missing target/style failures, lifecycle cleanup, idempotent shutdown |
| PPB | `tests/test_assets.py`: repeated engine setup and teardown through context managers | Explicit feature start/stop and teardown-before-root destruction |
| PPB | `tests/test_events.py`: invalid handler behavior and parametrized boundary cases | Invalid contribution metadata and clear conflict errors |
| Reference Expra | `tests/test_button_coordinator.py`: duplicate IDs, replacement, disabled dispatch, dead widgets, unregister, prefix cleanup | Direct coordinator compatibility and registry ownership cleanup |
| Reference Expra | `tests/test_ui_coordinator.py`: stale generations, owner changes, coalescing, visibility, shutdown, metrics | Render-target replacement/removal must not weaken coordinator safety |
| Reference Expra | `tests/test_app_coordinator.py`: coalescing, cancellation, stale results, idempotent shutdown, unsubscribe, latest-wins delivery | Feature lifecycle, callback cleanup, pending-intent invalidation |
| Ursina | Available `tests/test_load_blender_model/test_load_blender_model.py` only covers model loading | No contribution/editor edge-case contract was available to adopt |

## Required Cases

- Registry registration is validated before coordinator mutation.
- Duplicate action IDs, normalized shortcut sequences, empty IDs, missing
  action references, and missing style roles fail clearly.
- Unregister is idempotent and removes only state owned by that feature.
- Feature start/stop is idempotent; start failure rolls back registration and
  stop failure does not prevent other features from stopping.
- Direct `ButtonCoordinator` APIs remain usable without the registry.
- Disabled actions reject menu, toolbar, and shortcut activation equally.
- Unknown render targets are rejected before an intent is queued.
- Removed or replaced render targets cannot receive already-queued callbacks.
- Existing `UICoordinator` generation, owner, visibility, batching, priority,
  coalescing, stale rejection, and failure isolation remain unchanged.
- Test fixtures reset all registry/shared state between cases.

## Intentionally Not Adopted

- PPB's asset executor and global asset cache semantics are unrelated to editor
  contributions and are not introduced here.
- Ursina's editor implementation is not used as an architectural dependency;
  its available test archive does not provide relevant contribution coverage.
- Automatic plugin discovery, filesystem scanning, and a general event bus are
  outside this change.
