# Expra Scripting Maturity Design

**Goal:** Provide a safe, resource-backed gameplay scripting system whose common
path feels like `class PlayerBehaviour(Behaviour)` while preserving Expra's
engine, scene, clock, queue, filesystem, editor, and export ownership.

## Architecture

`ScriptComponent` stores only a project `ResourceId`, class name, enabled state,
ordering, and JSON-compatible exposed values. `ScriptRegistry` resolves trusted
project modules through normal import machinery and validates Behaviour classes.
`BehaviourSystem` is the single runtime owner: it creates one live instance per
component, supplies an explicit `BehaviourContext`, dispatches through the
existing `EventQueue`, and tears instances down exactly once.

The public convenience surface is deliberately small:

```python
class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)
    health = exposed(100, min=0, max=100)

    def on_update(self, dt: float) -> None:
        transform = self.require_component(TransformComponent)
        if self.input.is_held("move_right"):
            transform.x += self.speed * dt
```

Callbacks remain on the runtime thread. Update and fixed-update delivery use
the existing clock and queue. Dispatch uses stable snapshots and deferred
scene/entity mutation. Callback errors become structured diagnostics and follow
one documented runtime policy rather than being silently swallowed.

## Persistence and security

Live instances, callbacks, modules, closures, services, and timeline handles
are never serialized. Script resources use normalized project ResourceIds and
are included by export manifests. Serialized data cannot select arbitrary
modules, absolute paths, or executable expressions. Project Python is trusted
developer code; scene, save, dialogue, and exposed values remain data.

Hot reload, where supported, stages import and class validation first, then
replaces instances transactionally. A failed generation leaves the last known
good instance active.

## Editor and export

The inspector consumes generic exposed-property metadata and routes edits
through existing commands, so new Behaviour fields do not require coordinator
changes. Script attach/remove and creation are declarative editor contributions.
Export copies explicitly registered project script resources and uses the same
source/bytecode policy as the rest of the game project; editor/Tk modules are
excluded from shipped runtime profiles.

## Explicit non-goals

- No second event queue or runtime loop.
- No global scene, input singleton, or script-owned timer/thread.
- No Panda3D or Tk dependency in gameplay runtime.
- No serialized `eval`, `exec`, arbitrary imports, or filesystem paths.
- No hot reload that destroys known-good state before replacement validates.
- No Behaviour subclass treated as a `RuntimeSystem`.
