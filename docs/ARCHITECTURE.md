# Expra Engine Architecture

## Coordinator Architecture

| Coordinator | Owns | Source |
|---|---|---|
| `AppCoordinator` | Background work, coalescing, cancellation, lifecycle | Adapted from SA |
| `ButtonCoordinator` | UI action dispatch, widget enable/disable | Adapted from SA |
| `UICoordinator` | Presentation commits, stale-render rejection, batching | Adapted from SA |
| `ComponentRefreshScheduler` | When periodic work runs | Adapted from SA |

## Engine Model

| Concept | Owns |
|---|---|
| `Engine` | Run state (EDIT/PLAY/PAUSED), active scene, runtime isolation |
| `Project` | File structure, scene paths, assets dir |
| `Scene` | Entity list, create/remove/find, serialization |
| `Entity` | Stable UUID, name, enabled, component list |
| `Component` | Plain data; base for all component types |
| `TransformComponent` | 2D position, rotation, scale |

## Editor Panels

| Panel | Owns |
|---|---|
| Toolbar | Play/Pause/Stop buttons, project actions |
| HierarchyPanel | Entity list, add/delete, selection |
| InspectorPanel | Entity name/enabled, component fields |
| ViewportPanel | Canvas renderer (placeholder — architectural seam) |
| ConsolePanel | Log output |

## Action Flow

```
User action
    -> ButtonCoordinator.dispatch("action_id")
    -> registered callback
    -> engine mutation (scene/entity/transform change)
    -> panel.render() called (on main thread)
    -> Tk widget update
```

## Background Work Flow

```
Trigger (e.g. scene load)
    -> AppCoordinator.run("scene:load", task_factory)
    -> worker thread executes task_factory
    -> result delivered via deliver() -> main thread
    -> UICoordinator.request(RenderIntent)
    -> panel.render()
```

## Threading Invariant

**Tk owns widgets. Background work never touches widgets.**

- Workers run on background threads via AppCoordinator's ThreadPoolExecutor.
- Results cross to the main thread through the injected `deliver` callback.
- `deliver` calls `root.after_idle(callback)` which schedules execution on the Tk thread.
- No worker ever calls `widget.configure()` or any Tk API directly.

See `docs/THREADING.md` for full detail.

## Runtime Isolation (Play Mode)

When Play is pressed:
1. Engine deep-copies the edit scene through JSON round-trip.
2. The copy becomes the runtime scene.
3. Mutations during play affect only the runtime copy.
4. When Stop is pressed, the runtime copy is discarded; the edit scene is restored unchanged.

This prevents runtime simulation from corrupting the editor scene.
