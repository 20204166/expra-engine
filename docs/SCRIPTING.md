# Runtime Behaviours

`Behaviour` is the small, runtime-only contract for owner-bound gameplay code.
Subclass it and attach an instance to an `Entity` with an explicit factory:

```python
from expra_engine.runtime import Behaviour


class PlayerBehaviour(Behaviour):
    def on_update(self, event, signal):
        pass


player.add_behaviour(
    PlayerBehaviour(),
    runtime_factory=PlayerBehaviour,
)
```

The factory must be callable and must return a fresh, unowned `Behaviour`. On
`Engine.play()`, Expra captures factories before cloning the edit scene through
JSON, then creates and attaches new behaviour instances to matching runtime
entities. The edit-scene instances are not run.

## Lifecycle

For a runtime behaviour, callbacks occur in this order:

1. `on_attach(entity)` when the behaviour is attached.
2. `on_start()` when play begins, after runtime systems start and before the
   initial `SceneStarted` event.
3. `on_update(event, signal)` and `on_input(event, signal)` during dispatch.
4. `on_stop()` when play stops, after `SceneStopped` has been delivered.
5. `on_detach()` after `on_stop()`, before the runtime scene is discarded.

Behaviours are visited in entity order, then attachment order. Update and input
dispatch use a snapshot, so removing a behaviour during a callback does not
skip unrelated behaviours and the removed behaviour is not called later in the
same dispatch.

## Input

`on_input` receives the existing `ActionEvent`, including both `pressed` and
`released` phases. Return `True` to consume the event and stop delivery to
later eligible objects; return `False` to continue propagation. There is no
second input queue or input loop.

An entity must be enabled and a behaviour must be enabled for either update or
input delivery. Disabled entities and behaviours are skipped.

## Errors and Boundaries

Behaviour setup is fail-fast. Invalid or missing factories, factory failures,
non-`Behaviour` results, missing runtime entities, and reused instances raise
errors during `play()` before the engine leaves `EDIT`. Exceptions raised by
behaviour callbacks propagate unchanged.

Behaviours and their factories are runtime-only. They are not included in
`Entity.to_dict()`, scene JSON, or serialized component data. This slice does
not execute source code, load script files, discover scripts from serialized
data, or provide hot reload. Use normal Python imports and explicit factories
in the host application; safe serialization or reload would require a separate
contract.
