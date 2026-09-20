# Expra Gameplay Scripting

Project scripts are trusted developer Python. Scene files, saves, dialogue, and
exposed values are data and never become executable expressions.

## Public API

```python
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)
    health = exposed(100, min=0, max=100)

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        if self.input.is_held("move_right"):
            transform.x += self.speed * dt
```

`Behaviour` provides explicit access to its entity, scene, engine, semantic
`InputMap`, components, and the existing EventQueue through `emit()`. Use
`get_component`, `has_component`, and `require_component`; arbitrary attribute
magic is not part of the API.

Scripting is additive. Entities without a `ScriptComponent` continue through
their existing Expra components and runtime systems. A script can extend a
default operation, pass through when it has no decision, or explicitly claim a
customizable operation; only an explicit claim suppresses that operation's
default path. Scripts never replace the clock, queue, scene ownership,
physics, resource security, serialization, or renderer ownership. Removing or
disabling a script restores the documented default/fallback path.

## Lifecycle and timing

The canonical owner is one `BehaviourSystem`, not one runtime system per
script. A serialized `ScriptComponent` is resolved and instantiated when its
runtime scene starts. `on_start` runs once, `on_update(dt)` runs from the
variable `FrameUpdate`, `on_fixed_update(dt)` runs from the existing fixed
`RuntimeClock`, and `on_destroy` runs once before detachment. `on_enabled` and
`on_disabled` run only for transitions after start.

Entity and Behaviour enabled state both filter callbacks. Dispatch uses stable
snapshots. Mutations during callbacks are deferred by the owning scene/system,
so adding, removing, disabling, destroying, signalling, or requesting a scene
change cannot corrupt iteration or deliver stale scene events.

Play startup is atomic. If construction or `on_start` fails, already-started
instances are destroyed, runtime state is torn down, and the edit scene remains
active. Callback failures retain their cause and include script/resource,
class, entity, and callback context at the system boundary.

## Serialized scripts

`ScriptComponent` stores:

- `project://scripts/player.py` ResourceId
- Behaviour class name
- enabled state
- deterministic component order
- JSON-compatible exposed values

It never stores live instances, modules, callbacks, services, closures, or
timeline handles. Unknown exposed values are retained in scene data but ignored
by a newer class, so adding a default field is non-destructive. Incompatible
values fail validation rather than being silently coerced.

`ScriptRegistry` accepts only normalized `project://scripts/*.py` resources
inside the project root. It uses Python import machinery and validates the
requested class is a `Behaviour`. Absolute paths, traversal, symlink escapes,
arbitrary module names, `eval`, and serialized `exec` are rejected.

## Input, events, and existing runtime services

Scripts consume semantic actions such as `move_right`, not platform key names.
Input callbacks may return `PASS` to continue or `HANDLED`/`True` to consume
propagation. `emit()` delegates to
the existing FIFO `EventQueue`; Expra does not add a signal bus. Timelines,
tweens, sequences, repeaters, physics events, and the RuntimeClock remain
owned by their existing runtime services and must be cancelled or detached when
their Behaviour/entity/scene is destroyed.

## Editor and export

Exposed fields are metadata, not Tk widgets. The generic Inspector renders
stored script values and routes edits through stable-ID `CommandStack` commands,
so undo/redo is safe across selection changes and deleted entities. Script
creation and attachment use declarative editor tools and never overwrite files.

Project script files are included by the existing source/bytecode exporter. The
packaged runtime contains gameplay runtime modules only; editor, coordinator,
Tk, and delivery-queue modules are not runtime dependencies.

## Reload

Reload stages import and class validation before replacing live instances.
Compatible exposed values are transferred; private runtime state is not.
Syntax, import, class, dependency, stale-generation, and destroyed-entity
failures leave the last known-good instance active. The Ursina text-rewrite and
`exec` hot-reload design is intentionally not used.
