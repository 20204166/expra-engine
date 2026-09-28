# Behaviours and Scripting

Project scripts are trusted developer Python. Scene files, saves, and exposed
values are data — never executable expressions.

## Minimal example

```python
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        if self.input.is_held("move_right"):
            transform.x += self.speed * dt
```

Attach it by adding a `ScriptComponent` with `script_id="project://scripts/player.py"`
and `behaviour_class="PlayerBehaviour"`.

## Access and context

`Behaviour` provides:

- `self.entity` / `self.scene` / `self.engine`;
- `get_component(cls)`, `has_component(cls)`, `require_component(cls)` (raises
  `LookupError`);
- `self.input` — the engine's `InputMap` (`is_held(action)`, `held_actions`);
- `emit(event)` — enqueue an event on the engine's `EventQueue`.

There is no arbitrary attribute magic.

## Lifecycle callbacks

| Method | When |
|---|---|
| `on_attach(entity)` | bound to an entity |
| `on_start()` | once, when the runtime scene starts |
| `on_update(dt)` | variable `FrameUpdate` |
| `on_fixed_update(dt)` | fixed-step `Update` from the clock |
| `on_enabled()` / `on_disabled()` | enabled-state transitions after start |
| `on_event(event)` | queued events |
| `on_input(event, signal) -> bool` | input action events |
| `on_stop()` / `on_destroy()` / `on_detach()` | teardown |

`on_input` returns `PASS` (default, `False`) or `HANDLED` (`True`); returning
`True` consumes the event and stops propagation.

## `exposed` fields

`exposed(default, *, min, max, step, tooltip, category, readonly, choices)` marks
a class attribute as an inspector-editable parameter. Values are stored in
`instance._exposed_values` and validated for type/range/choice. The Inspector
renders these (booleans as checkbuttons, others as entries). `exposed_schema()`
collects them across the MRO.

## Serialization

`ScriptComponent` stores `script_id`, `behaviour_class`, `enabled`, an
`order`, and JSON-compatible `exposed_values`. It never stores live instances,
modules, closures, or timeline handles. Unknown exposed values are retained but
ignored; incompatible values fail validation.

`ScriptRegistry` only accepts `project://scripts/*.py` inside the project root,
uses normal import machinery, and validates the class is a `Behaviour`.
Absolute paths, traversal, `eval`, and serialized `exec` are rejected.

## Ownership and isolation

The canonical owner is one `BehaviourSystem`, not one system per script. A
serialized `ScriptComponent` is resolved and instantiated when its runtime scene
starts. Dispatch uses stable snapshots; mutations are deferred. Play startup is
atomic — if construction or `on_start` fails, started instances are destroyed
and the edit scene remains active.

Removing or disabling a script restores the documented default/fallback path.
Scripts never replace the clock, queue, physics, resource security,
serialization, or renderer ownership.

## Reload

Reload stages import + class validation before replacing live instances.
Compatible exposed values transfer; private runtime state does not. On failure,
the last known-good instance stays active.

## Anti-patterns

- Importing editor/Tk modules into a runtime script.
- Manually parsing `.pb` files.
- Using `TextComponent` as game state.
- Global mutable state where a runtime owner already exists.
- Scanning files every frame (use the resource system).
- Relying on entity `name` for identity.
- Forgetting to cancel/detach timelines, tweens, or sequences on destroy.
