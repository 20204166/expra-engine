# Behaviour Runtime Core Design

Status: approved design; implementation plan pending user review.

## Goal

Add a small, reusable gameplay behaviour runtime to Expra. Behaviours are
standalone runtime objects attached to entities. They provide executable game
logic without turning serialized components into executable source or adding a
second runtime loop.

## Scope

The first slice includes:

- A typed `Behaviour` base contract.
- Ordered attachment and removal on `Entity`.
- Behaviour lifecycle callbacks for attach, play start, update, input, play
  stop, and detach.
- Disabled entity/behaviour filtering.
- Explicit boolean input consumption.
- Fail-fast callback exceptions.
- Regression tests for ordering and lifecycle edge cases.

The first slice excludes:

- Behaviour serialization or arbitrary source loading.
- Inspector-exposed behaviour properties.
- Hot code reload.
- Background worker execution.
- New event queues, runtime loops, or global scene state.
- Scene-specific callbacks beyond the existing engine start/stop boundaries.

## Contract

The public base class will be a standalone runtime object, conceptually:

```python
class Behaviour:
    entity: Entity | None
    enabled: bool

    def on_attach(self, entity: Entity) -> None: ...
    def on_start(self) -> None: ...
    def on_update(self, event: Update, signal: Signal) -> None: ...
    def on_input(self, event: ActionEvent, signal: Signal) -> bool: ...
    def on_stop(self) -> None: ...
    def on_detach(self) -> None: ...
```

Default callbacks are no-ops and `on_input` returns `False`. A behaviour has
one owner at a time. Attaching an already-owned behaviour is rejected rather
than silently reparenting it. Removing an absent behaviour is a no-op or a
false result, matching the existing `Entity.remove_component` ergonomics.

Each attached behaviour also declares a runtime factory that returns a fresh,
unowned behaviour instance. The factory is used when the engine creates the
isolated runtime scene; it must not return the edit-scene instance.

Input callbacks receive the existing backend-neutral `ActionEvent` from
`runtime.input`; the behaviour API does not invent a second input abstraction.

## Ownership and Dispatch

- `Entity` owns an ordered list of behaviours separately from data components.
- `Entity.add_behaviour()` calls `on_attach()` after ownership is established.
- `Engine` captures the attached behaviour factories before JSON-cloning the
  edit scene, then instantiates fresh behaviours onto matching runtime
  entities by stable entity ID.
- `Engine` invokes `on_start()` for behaviours reachable from the runtime
  scene when entering PLAY.
- Existing event dispatch remains canonical. Behaviour dispatch is exposed via
  the existing `on_update` and input paths rather than a new queue.
- Update callbacks run in stable entity/attachment order.
- Input callbacks run in stable entity/attachment order. A truthy return value
  stops later input delivery for that dispatch.
- A disabled entity or disabled behaviour receives neither update nor input.
- `on_stop()` runs once when PLAY ends, before runtime scene teardown.
- `on_detach()` runs once when a behaviour is removed from its owner or when
  the runtime owner is torn down; runtime clones do not reattach the edit-scene
  behaviour objects.
- Callback exceptions propagate through the existing event/tick path. The
  runtime does not silently disable a failing behaviour or aggregate errors.

Dispatch must tolerate removal during a callback without skipping unrelated
behaviours or invoking a removed behaviour later in the same dispatch. The
implementation should use a stable dispatch snapshot or an equivalent
explicit rule, covered by tests.

## Serialization Boundary

Behaviours are runtime objects in this slice and are not serialized into
`Entity.to_dict()`. Existing data components remain the only serialized
component model. Runtime scene copying on `Engine.play()` uses the explicit
factory associated with each attached behaviour. If a behaviour has no safe
factory, `Engine.play()` fails clearly before entering PLAY rather than copying
executable objects or silently omitting required gameplay logic.

This boundary is intentional. Behaviour discovery, factories, exposed
properties, and export integration are follow-up work requiring a separate
design.

## Testing Requirements

Tests must establish:

- Attach calls exactly once and establishes the owner before the callback.
- Duplicate or cross-owner attachment is rejected.
- Runtime scene cloning creates fresh behaviour instances through explicit
  factories and preserves matching stable entity ownership.
- A missing runtime factory fails before PLAY begins and leaves edit state
  intact.
- Start/stop/detach ordering is deterministic.
- Updates reach enabled behaviours in entity/attachment order.
- Disabled entities and behaviours are filtered.
- Input returns `False` to continue and `True` to consume.
- Removal during update/input does not skip the next eligible behaviour and
  does not invoke the removed behaviour after removal.
- Exceptions propagate unchanged through event/tick dispatch.
- Runtime stop calls `on_stop()` before detaching runtime behaviours with
  `on_detach()`.
- Existing engine, event queue, scene, and serialization tests remain green.

## Alternatives Rejected

- Behaviour-as-component was rejected for this slice because executable
  runtime state should not be treated as JSON scene data.
- Entity method conventions were rejected because they prevent reusable
  composition and make lifecycle ownership implicit.
- Ursina-style string-only `"key up"` conventions, Panda3D/Tk coupling, and
  `exec`-based hot reload were rejected by the source audit and project
  constraints.
