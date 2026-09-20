# Expra Scripting Source Audit

Status: audit complete; implementation not started.

This document records the read-only audit required before adding gameplay
scripting or behaviour support to Expra. Reference repositories were not
modified.

## Scope and Constraints

Audited sources:

- Expra: `src/expra_engine/`, `tests/`, `examples/`, `docs/`
- Ursina: `/home/btn17/Downloads/ursina-master`
- PursuedPyBear: `/home/btn17/Downloads/pursuedpybear-canon`
- MiniPyEngine: `/home/btn17/Downloads/MiniPyEngine-main`
- Additional local reference: `/home/btn17/Downloads/exp`

Expra must retain the following ownership boundaries:

- One canonical Expra event queue and runtime loop.
- `Engine`, `Scene`, `Entity`, `Component`, and runtime systems remain the
  owners of lifecycle and scheduling.
- No second event queue, hidden global scene, or framework-owned runtime loop.
- No Panda3D or Tk runtime dependency in the shipped game runtime.
- No `eval` or `exec` for serialized project or script data.
- Reference repositories remain read-only.

## Current Expra Baseline

Expra already provides the foundations that a scripting layer must use rather
than replace:

- `src/expra_engine/core/project.py`: project ownership and persistence entry.
- `src/expra_engine/core/scene.py`: scene hierarchy, stable IDs, cloning,
  component queries, and JSON-compatible scene data.
- `src/expra_engine/core/entity.py`: entity hierarchy, transforms, components,
  stable IDs, and serialization boundaries.
- `src/expra_engine/core/component.py`: component base and attachment model.
- `src/expra_engine/core/engine.py`: EDIT/PLAY/PAUSED state, scene stack,
  ticking, lifecycle, and play-mode ownership.
- `src/expra_engine/runtime/events.py`: queued event dispatch, named handlers,
  targeted delivery, FIFO ordering, and lifecycle events.
- `src/expra_engine/runtime/event_queue.py`: the canonical event queue.
- `src/expra_engine/runtime/system.py`: runtime-system lifecycle and ownership.
- `src/expra_engine/runtime/input.py`: backend-neutral input mapping.
- `src/expra_engine/core/safe_expression.py`: restricted expression support;
  this is not an arbitrary script executor.
- `src/expra_engine/editor/inspector.py` and contribution registries: existing
  editor extension seams.

There is currently no dedicated `Script`, `Behavior`/`Behaviour`, behaviour
system, script registry, exposed-script-property schema, script-specific
export/discovery, or hot-code-reload implementation.

## Reference Findings

### Ursina

Evidence: `ursina/entity.py`, `ursina/main.py`, `ursina/destroy.py`,
`ursina/sequence.py`, `ursina/prefabs/hot_reloader.py`, and the samples/scripts
under `ursina/` and `samples/`.

Useful patterns:

- Convention-based owner methods: `update()` and `input(key)`.
- Reusable owner-bound scripts attached through `Entity.add_script()`.
- Host-owned dispatch applies enabled, ignored, paused, and disabled-ancestor
  filtering before calling entity scripts.
- Truthy input return values consume propagation.
- Practical lifecycle hooks such as `on_enable`, `on_disable`, and
  `on_destroy`.
- Sequence-based animation and delayed work tied to entity ownership.
- Hot reload preserves the process/window in development mode.

Important limitations not to copy:

- Scripts are tightly coupled to Panda3D-backed entities and lack a complete
  independent lifecycle protocol.
- Release input is routed through `input()` as `"key up"`; there is no real
  `input_up()` contract.
- Destruction is deferred from the scene list and can leave Python references
  alive.
- Ordinary entity animation ownership is inconsistent for pause filtering.
- Hot reload uses `exec`, clears/rebuilds scenes, and can leave the app paused
  after failure. It also contains a broken path-existence check.
- Automated coverage for input propagation, destruction ordering, script
  cleanup, and hot-reload failure is sparse.

### PursuedPyBear

Evidence: `src/ppb/engine.py`, `src/ppb/events.py`, `src/ppb/systemslib.py`,
`src/ppb/gomlib.py`, `src/ppb/scenes.py`, and `tests/test_engine.py` plus the
related test modules.

Useful patterns:

- A single engine-owned queue and synchronous drain boundary.
- Explicit `SceneStarted`, `ScenePaused`, `SceneContinued`, and `SceneStopped`
  lifecycle events.
- Scene transitions flush stale queued events before ownership changes.
- Event handlers use a predictable `on_<event_name>(event, signal)` convention.
- Targeted events use weak references, avoiding retention of transient objects.
- Systems are explicit engine-owned context managers.
- Protocol-like rendering permits objects to participate without inheriting a
  rigid renderer base.
- Tests cover scene transitions, event routing, validation, and timeouts.

Important limitations not to copy:

- Systems are stored in a set, so system traversal/context order is not
  deterministic.
- Targeted delivery can reach objects outside the active tree by design.
- Event dispatch is concrete-name based rather than inheritance based.
- Scenes and systems are deliberately not ordinary children and have separate
  mutation rules.
- The engine duplicates child-container logic and retains acknowledged
  renderer/image coupling.

### MiniPyEngine

Evidence: `Engine/StartGame.py`, `Engine/objects/GameObjectBase.py`,
`Engine/objects/GameObjects.py`, `Engine/objects/Level1.py`, and `README.md`.

Useful patterns:

- Small Python object contract with `update(delta_time, game_objects)`.
- Central object collection and simple deferred-destruction flag.
- Human-readable map data with explicit object fields.
- Direct subclassing is easy for developers who control engine source.

Important limitations:

- No attachable scripts, components, reflection metadata, inspector, safe
  serialization, or hot reload.
- Map type dispatch is hard-coded and malformed data can raise uncaught
  exceptions.
- Removal while iterating can skip an object.
- Collision and gravity behavior is implemented in selected concrete classes,
  not through a reusable runtime protocol.

### `/home/btn17/Downloads/exp`

This repository is System Analyzer, not an older Expra game-engine runtime.
Evidence includes its `README.md`, `main.py`, `window.py`, and `AGENTS.md`.

Reusable non-game patterns:

- Composition-root ownership in `window.py`.
- `maintenance/components/coordinator.py`: explicit scheduling state,
  coalescing, cancellation, in-flight protection, and stale-generation
  rejection.
- `maintenance/components/catalog.py`: deterministic registries with duplicate
  and unknown-key validation.
- `maintenance/persistence.py`: atomic persistence.
- Tests use fake clocks/runners/widgets and exercise late results, cancellation,
  destroyed UI targets, and lifecycle stress.

It contains no entity, scene, gameplay input, behaviour attachment, script
execution, safe user-script reload, or game-runtime export model.

## Parity and Action Matrix

Classification:

- A: adopt the useful concept through existing Expra ownership.
- B: adapt only after resolving a concrete Expra difference.
- C: reject because it violates Expra constraints or has unsafe semantics.
- D: defer until a concrete product need and test seam exist.
- E: already present in Expra; do not duplicate it.

| Capability | Reference evidence | Expra status | Class | Action |
|---|---|---|---|---|
| Owner-bound behaviour object | Ursina `entity.py:add_script` | No dedicated type | A | Add a small owner-bound behaviour contract using existing components/entities. |
| Per-frame update | Ursina `main.py`; MiniPyEngine `GameObjectBase.py` | Existing engine tick/events | E/A | Route behaviour updates through the existing engine tick, not a new loop. |
| Input callbacks | Ursina `main.py` | Existing input/event layer | A/E | Define explicit behaviour input semantics on top of canonical input dispatch. |
| Input consumption | Ursina `main.py` truthy return | No script-specific contract | A | Specify and test deterministic propagation/consumption. |
| Explicit release callback | Ursina `"key up"` convention | No behaviour contract | B | Prefer an explicit event or documented callback; do not copy the string-only convention blindly. |
| Enable/disable filtering | Ursina `Entity.enabled` and ancestor checks | Engine/entity state exists | A/E | Reuse entity/component enabled state and document inherited behavior. |
| Start/attach lifecycle | Ursina `on_script_added`; PPB scene events | No script lifecycle | A | Add only the hooks required by ownership and test ordering. |
| Destroy cleanup | Ursina `destroy.py` | Entity/component lifecycle exists | A/B | Define cleanup ordering and removal guarantees before implementation. |
| Scene lifecycle | PPB `engine.py`/`events.py` | Existing scene lifecycle events | E | Bind behaviours to existing lifecycle events; no parallel scene protocol. |
| Behaviour scheduling | `/home/btn17/Downloads/exp` coordinator | Runtime systems exist | B | Borrow explicit state/coalescing ideas only if asynchronous work is required. |
| Registry/discovery | `/home/btn17/Downloads/exp` catalog | Contribution registries exist | A/E | Reuse contribution/registry seams; reject hidden global registries. |
| Exposed properties | Expra inspector and serialization | Partial inspector/model support | A | Define a safe, serializable property schema; no arbitrary code execution. |
| Script serialization | None of the references safely implement this | JSON-compatible scene data exists | A | Serialize stable type IDs and validated data, not executable source. |
| Hot code reload | Ursina `hot_reloader.py` | Not present | C/D | Reject `exec`-based runtime reload; defer safe module reload until explicitly needed. |
| Animation/tween ownership | Ursina `sequence.py` | Existing timeline/tween systems | E | Integrate behaviours with existing timing systems. |
| Error isolation | PPB synchronous propagation; Ursina propagation | No behaviour-specific policy | B | Decide whether behaviour errors fail-fast or are reported/disabled, then test it. |
| Background work | `/home/btn17/Downloads/exp` coordinator | No gameplay need established | D | Do not add worker scheduling to behaviours without a concrete use case. |
| Editor inspector integration | `/home/btn17/Downloads/exp` has no game inspector; Expra has one | Existing inspector | A/E | Extend current inspector metadata only for validated exposed properties. |
| Export/discovery | MiniPyEngine hard-coded map types | Expra export exists | A | Add explicit script/behaviour discovery to export only after runtime identity is defined. |
| Separate event loop | PPB has one engine loop; Ursina has one app loop | Expra has one loop | C/E | Never add another loop or queue. |
| Panda3D/Tk coupling | Ursina/PyMini references | Expra backend-neutral runtime | C | Do not import either framework into shipped gameplay runtime. |

## Proposed Minimal Direction

The smallest defensible next implementation is:

1. Define a typed, owner-bound behaviour contract with explicit attach,
   enable/disable, update, input, and destroy semantics.
2. Register and invoke it from existing `Entity`/`Component` ownership and the
   existing `Engine`/event/timing paths.
3. Define validated exposed-property metadata that remains JSON-compatible.
4. Add tests first for ordering, disabled owners, input consumption, removal
   during dispatch, scene transitions, and exceptions.
5. Add editor and export integration only after the runtime contract is stable.

Do not implement hot reload, arbitrary source execution, or background script
workers as part of this initial slice.

## Evidence Gaps

Before implementation, inspect and cite the exact current Expra call sites for:

- Entity/component attach and removal ordering.
- Engine tick and event dispatch ordering.
- Existing runtime systems for animation/tween and physics ownership.
- Inspector property validation and serialization restrictions.
- Export asset/module discovery.

These call sites determine the final method names and test seams; the parity
matrix above intentionally avoids inventing API names before that verification.
