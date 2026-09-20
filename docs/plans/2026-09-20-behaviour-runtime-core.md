# Behaviour Runtime Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone, owner-bound gameplay behaviours with deterministic lifecycle, update, input, runtime cloning, and fail-fast error semantics.

**Architecture:** `Behaviour` is a runtime-only object owned by `Entity`, separate from serialized data components. Existing `Engine`, `EventQueue`, `RuntimeClock`, and `ActionEvent` remain the only lifecycle, timing, and input paths; `Engine.play()` captures explicit factories before JSON scene cloning and attaches fresh behaviours to matching runtime entities.

**Tech Stack:** Python 3.12, dataclasses/type hints, pytest, existing Expra event queue and scene model.

---

## File Structure

- Create `src/expra_engine/runtime/behaviour.py`: public behaviour contract and factory typing.
- Modify `src/expra_engine/runtime/__init__.py`: export the public behaviour type.
- Modify `src/expra_engine/core/entity.py`: ordered runtime behaviour ownership and lifecycle helpers.
- Modify `src/expra_engine/core/engine.py`: capture factories, attach runtime instances, and stop/detach them.
- Modify `src/expra_engine/runtime/event_queue.py`: invoke behaviour update/input dispatch through existing queue traversal without adding a queue.
- Modify `tests/test_entity.py`: attachment and ownership tests.
- Modify `tests/test_engine_runtime.py`: play cloning and lifecycle tests.
- Create `tests/test_runtime_behaviour.py`: focused dispatch, filtering, input, mutation, and failure tests.

## Task Outline

### Task 1: Define the runtime behaviour contract

Add the typed base class, factory protocol, default no-op callbacks, and
ownership/enable state. Export it without changing serialized component APIs.

**Files:**
- Create: `src/expra_engine/runtime/behaviour.py`
- Modify: `src/expra_engine/runtime/__init__.py`
- Test: `tests/test_runtime_behaviour.py`

- [ ] **Step 1: Write the failing contract tests**

Create a minimal subclass whose callbacks append to a log. Assert a new
behaviour starts with `entity is None`, `enabled is True`, no-op callbacks do
not raise, and the default input result is `False`.

- [ ] **Step 2: Run the focused test**

Run: `pytest tests/test_runtime_behaviour.py -q`
Expected: FAIL because the behaviour module and public type do not exist.

- [ ] **Step 3: Implement the contract**

Define `Behaviour`, `BehaviourFactory`, and the callback signal type. Keep the
class runtime-only; do not add `to_dict`, registry registration, or source
execution. `on_input` accepts `ActionEvent` and returns `False` by default.

Target shape:

```python
Signal = Callable[[object], None]

class Behaviour:
    entity: Entity | None = None
    enabled: bool = True

    def on_attach(self, entity: Entity) -> None: ...
    def on_start(self) -> None: ...
    def on_update(self, event: Update, signal: Signal) -> None: ...
    def on_input(self, event: ActionEvent, signal: Signal) -> bool: return False
    def on_stop(self) -> None: ...
    def on_detach(self) -> None: ...

BehaviourFactory = Callable[[], Behaviour]
```

- [ ] **Step 4: Export and verify**

Export `Behaviour` and `BehaviourFactory` from the runtime package, then run:
`pytest tests/test_runtime_behaviour.py -q`
Expected: PASS.

### Task 2: Add entity behaviour ownership

Add ordered attachment/removal/query methods. Establish ownership before
`on_attach`, reject duplicate or cross-owner attachment, and detach exactly
once on removal.

**Files:**
- Modify: `src/expra_engine/core/entity.py`
- Test: `tests/test_entity.py`

- [ ] **Step 1: Write attachment tests**

Test that `add_behaviour()` stores behaviours in insertion order, sets
`behaviour.entity` before calling `on_attach`, rejects a second attachment to
the same entity and attachment to another entity, and that removal returns
`True`, clears ownership after `on_detach`, and returns `False` when absent.

- [ ] **Step 2: Run the entity tests**

Run: `pytest tests/test_entity.py -q`
Expected: FAIL with missing behaviour ownership methods.

- [ ] **Step 3: Implement ordered ownership**

Add a private behaviour list, an immutable tuple property, `add_behaviour`,
`remove_behaviour`, and type-based lookup. Accept a required runtime factory
when attaching; reject factories that are not callable. Call `on_attach` only
after the owner and list entry are established.

Target call shape:

```python
entity.add_behaviour(behaviour, runtime_factory=PlayerBehaviour)
entity.remove_behaviour(behaviour)  # True when removed
entity.get_behaviour(PlayerBehaviour)
```

- [ ] **Step 4: Verify existing entity behavior**

Run: `pytest tests/test_entity.py tests/test_scene.py -q`
Expected: PASS, with `Entity.to_dict()` unchanged and data component behavior
unaffected.

### Task 3: Add failing lifecycle and cloning tests

Use test doubles with event logs and explicit factories to specify attach,
start, update, stop, detach, disabled filtering, and play-mode isolation.

**Files:**
- Modify: `tests/test_engine_runtime.py`
- Test support: `tests/test_runtime_behaviour.py`

- [ ] **Step 1: Add lifecycle test fixtures**

Define a test behaviour with a factory returning a fresh instance and callbacks
that record `(instance, callback, entity_id)` tuples. Build a scene with two
entities and attach behaviours in a known order.

- [ ] **Step 2: Add play-copy tests**

Assert `engine.play()` creates a runtime entity with the same stable ID but a
different behaviour instance, calls attach/start on the runtime instance, and
does not mutate the edit scene. Assert a behaviour without a factory raises a
clear `ValueError` while the engine remains in `EDIT`.

- [ ] **Step 3: Add stop ordering tests**

Assert `engine.stop()` calls runtime `on_stop` before runtime `on_detach`, and
that the original edit-scene behaviour is neither started nor stopped.

- [ ] **Step 4: Run the new tests before implementation**

Run: `pytest tests/test_engine_runtime.py tests/test_runtime_behaviour.py -q`
Expected: the new behavior-specific tests FAIL while existing engine tests
continue to pass.

### Task 4: Implement engine runtime cloning and lifecycle

Capture factories before JSON cloning, attach fresh instances by stable ID,
start them before normal PLAY dispatch, then stop and detach them before the
runtime scene is discarded. Missing factories must leave EDIT state intact.

**Files:**
- Modify: `src/expra_engine/core/engine.py`

- [ ] **Step 1: Add a factory capture helper**

Walk the edit scene entities and store each entity ID with its ordered
`(behaviour, factory)` pairs before `_copy_scene()` runs. Validate every
factory and fail before changing `_state`, `_runtime_scene`, or runtime
systems.

- [ ] **Step 2: Add runtime attachment after JSON cloning**

After `Scene.from_dict()` returns, resolve each captured entity ID in the
runtime scene and call the factory. Require a fresh unowned `Behaviour`, attach
it with the same factory, and raise a descriptive error for missing IDs,
factory failures, wrong return types, or reused instances.

The helper must leave the edit scene untouched and attach each fresh instance
through the normal `Entity.add_behaviour()` path so `on_attach` remains the
single ownership boundary.

- [ ] **Step 3: Add start and stop helpers**

Start runtime behaviours after the runtime scene/queue exists and before the
first normal frame. During `_stop_runtime`, call `on_stop` and detach every
runtime behaviour before clearing the queue and runtime references. Preserve
existing reverse system-stop ordering.

- [ ] **Step 4: Run lifecycle tests**

Run: `pytest tests/test_engine_runtime.py tests/test_runtime_behaviour.py -q`
Expected: PASS.

### Task 5: Add update and input dispatch tests

Specify deterministic order, boolean input consumption, removal during
dispatch, and callback exception propagation.

**Files:**
- Modify: `tests/test_runtime_behaviour.py`
- Modify: `tests/test_runtime_input.py`

- [ ] **Step 1: Test update order and filtering**

Signal `Update` through an active runtime scene and assert callbacks run in
entity order then attachment order. Disable one entity and one behaviour and
assert neither receives the event.

- [ ] **Step 2: Test input consumption**

Dispatch an `ActionEvent(phase="pressed")`; assert `False` continues to the
next eligible behaviour and `True` stops later behaviour delivery. Confirm
release events use the same existing `ActionEvent` path.

- [ ] **Step 3: Test mutation and exceptions**

Have one callback remove the next behaviour and assert unrelated callbacks are
not skipped and the removed callback is not invoked after removal. Have a
callback raise a sentinel exception and assert it propagates unchanged.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_runtime_behaviour.py tests/test_runtime_input.py -q`
Expected: FAIL until event dispatch integration is implemented.

### Task 6: Integrate dispatch through existing events

Route `Update` and `ActionEvent` through the existing event traversal while
respecting entity/behaviour enabled state and stable snapshots.

**Files:**
- Modify: `src/expra_engine/runtime/event_queue.py`
- Modify: `src/expra_engine/core/entity.py`
- Modify: `src/expra_engine/runtime/events.py` only if an existing event type
  needs a narrowly scoped annotation/export adjustment

- [ ] **Step 1: Add entity event adapters**

Add `Entity.on_update(event, signal)` to snapshot and invoke enabled
behaviours. Add `Entity.on_action_event(event, signal)` to invoke
`on_input`; return `True` on the first consumed input. These adapters keep
behaviour-specific method names out of `EventQueue` and use the existing
`ActionEvent` type from `runtime.input`.

- [ ] **Step 2: Preserve event handler routing and consumption**

Keep existing object handlers working. In `EventQueue.publish()`, capture a
handler return value only for `ActionEvent`; stop the current broadcast when
an object returns truthy. Do not change return handling for `Update`, lifecycle,
or unrelated event classes.

- [ ] **Step 3: Make mutation semantics explicit**

Use a per-dispatch snapshot and check current ownership/enabled state before
invoking each behaviour. This prevents removed behaviours from running while
allowing newly attached behaviours to participate on the next dispatch.

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest tests/test_event_queue.py tests/test_runtime_events.py tests/test_runtime_behaviour.py -q`
Expected: PASS, including existing event signature and FIFO tests.

### Task 7: Verify and document the public contract

Run focused and full tests, type/lint checks when available, inspect the diff,
and add concise user-facing scripting documentation without promising excluded
serialization or hot-reload features.

**Files:**
- Create: `docs/SCRIPTING.md`
- Modify: `src/expra_engine/runtime/__init__.py` if public exports are incomplete
- Test: existing full suite

- [ ] **Step 1: Document the supported contract**

Document behaviour construction, explicit runtime factories, lifecycle order,
`ActionEvent` input consumption, enabled filtering, fail-fast errors, and the
fact that behaviours are runtime-only in this slice.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: all existing and new tests pass.

- [ ] **Step 3: Run static checks**

Run: `ruff check src tests` and `pyright`.
Expected: no new diagnostics. If a tool is unavailable, record that fact and
use the available project checks instead.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check` and `git status --short`; confirm only the behaviour
implementation, tests, documentation, and this plan are changed. Do not
commit unless explicitly requested.
