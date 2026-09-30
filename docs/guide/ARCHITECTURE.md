# Architecture

Expra Engine separates game state, coordination, runtime services, and editor
presentation into layers with strict ownership boundaries.

```
┌───────────────────────────────────────────────────────────────┐
│  Editor Layer  (PySide6 / Qt)                                 │
│  Qt EditorWindow · panels · QtDeliveryQueue · preferences    │
├───────────────────────────────────────────────────────────────┤
│  Coordinator Layer  (toolkit-independent Python)              │
│  AppCoordinator · ButtonCoordinator · UICoordinator           │
│  ComponentRefreshScheduler · PendingTransition                │
├───────────────────────────────────────────────────────────────┤
│  Runtime Layer  (headless Python)                              │
│  EventQueue · RuntimeClock · BehaviourSystem · world streaming│
│  physics · renderer protocol · Pygame adapter                 │
├───────────────────────────────────────────────────────────────┤
│  Engine Core  (headless Python)                                │
│  Engine · Project · World · Level · Scene · Entity · Component│
│  Camera2D · document codec · filesystem                       │
└───────────────────────────────────────────────────────────────┘
```

The hard rule: **`core/`, `coordinators/`, `runtime/`, `filesystem/`, and
`export/` do not import GUI toolkits.** The Qt editor owns widget presentation;
shared editor logic remains separate from the shell. This keeps the engine
importable in headless contexts (tests, exported runtime, MCP static runner).

## Ownership matrix

| Responsibility | Owner | Module |
|---|---|---|
| Game state (project/scene/world, entities) | `Engine` | `core/engine.py` |
| Project manifest + document registries | `Project` | `core/project.py` |
| Reusable entity composition | `Scene` | `core/scene/scene.py` |
| Playable place (Scene + metadata) | `Level` | `core/scene/level.py` |
| Geography / connectivity / residency | `World` | `core/world.py` |
| Entity lifecycle + components + behaviours | `Entity` | `core/entity.py` |
| Component data + registry | `Component` subclasses | `core/component.py` |
| Editor authoring schema | `ComponentTypeSpec` | `core/component_schema.py` |
| JSON ↔ Protobuf conversion | codec | `core/scene/document_codec.py` |
| Runtime event dispatch | `EventQueue` | `runtime/event_queue.py` |
| Fixed-step clock | `RuntimeClock` | `runtime/clock.py` |
| Serialized gameplay scripts | `BehaviourSystem` | `runtime/behaviour_system.py` |
| Script resource validation | `ScriptRegistry` | `runtime/script_registry.py` |
| Physics queries / triggers | `PhysicsWorld2D` | `runtime/physics_world.py` |
| World loading / residency / travel | `WorldStreamingSystem` | `runtime/world_streaming.py` |
| Renderer protocol + descriptors | `rendering` | `runtime/rendering.py` |
| Authored → RenderFrame | `extract_render_frame` | `runtime/render_extractor.py` |
| RenderFrame → operations | `RenderPlanBuilder` | `runtime/render_pipeline.py` |
| Pygame backend | `PygameRenderer` | `runtime/pygame_renderer.py` |
| Asset bytes / logical IDs | `ResourceService` | `filesystem/service.py` |
| Background work scheduling | `AppCoordinator` | `coordinators/app_coordinator.py` |
| Action dispatch + enable/disable | `ButtonCoordinator` | `coordinators/button_coordinator.py` |
| UI update batching | `UICoordinator` | `coordinators/ui_coordinator.py` |
| Qt editor startup | `run_qt_editor` | `editor/qt/app.py` |
| Project open/create/save flow | `ProjectWorkflow` | `editor/project_workflow.py` |
| World authoring | `WorldAuthoringWorkflow` | `editor/world_authoring.py` |
| Editor shell + shared behavior | `EditorWindow` / `EditorWindowCore` | `editor/qt/main_window.py`, `editor/window_core.py` |
| Hierarchy / Inspector / Viewport / Console | Qt panels + shared cores | `editor/qt/`, `editor/*_core.py` |
| Export pipeline | `GameExporter` | `export/exporter.py` |
| Runtime metrics | `ObservabilityWatcher` | `observability.py` |

## Threading model

**Qt widgets are GUI-thread-owned.** Background work never touches widgets.
Results cross from worker threads through `AppCoordinator` → `QtDeliveryQueue`
→ `UICoordinator` and are applied on the Qt GUI thread.

```
Worker thread                      Qt GUI thread
──────────────                     ─────────────
AppCoordinator._run_worker()
  → on_result
    → deliver(callback)            QtDeliveryQueue._drain()
      → queue.put(callback)  ──►     → callback()
                                       → UICoordinator.request()
                                         → panel.render()
                                            → widget.set...(…)
```

`QtDeliveryQueue.__call__` is the worker → UI entry point. See
[THREADING.md](../THREADING.md) for the full model.

## Coordinators

- **AppCoordinator** — runs background work in a thread pool; coalesces repeated
  runs per key; drops stale generations; delivers via `deliver=` callable.
- **ButtonCoordinator** — maps action ids to callables with enabled state;
  `register`, `dispatch`, `set_enabled`.
- **UICoordinator** — batches render intents; deduplicates per target; rejects
  stale generations; `request`, `begin_batch`/`end_batch`, `invalidate`.
- **ComponentRefreshScheduler** — tracks when periodic refresh work is due.

## Runtime model

The runtime is headless and driven by the caller through `Engine.tick()` (alias
`loop_once()`). `Engine.tick()` signals `FrameUpdate(dt)` then `Idle(dt)`, then
drains the `EventQueue`. `RuntimeClock` converts `Idle` into fixed-step `Update`
events via an accumulator. `FrameUpdate` carries variable frame time.

Actionable events are queued requests:

- `StartScene` / `StopScene` / `ReplaceScene` / `Quit`.

Lifecycle notifications: `SceneStarted`, `SceneStopped`, `ScenePaused`,
`SceneContinued`.

## Play / Stop isolation

- **Play** deep-copies the edit scene (a JSON round-trip) and puts the copy on
  the runtime scene stack. The edit scene stays owned by the editor.
- **Stop** discards the runtime scene stack; the edit scene is restored.

When a World is configured, Play instead uses
`WorldStreamingSystem.runtime_scene`. See [Play vs Run Project](PLAY_AND_RUN_PROJECT.md).

## Packaging boundary

The wheel ships `expra_engine/` with `core/`, `coordinators/`, `runtime/`,
`editor/`, `ui/`, `filesystem/`, `messages/`, `schema/`, `ui_model/`, `design/`,
`export/`. The export runtime stages only the headless subset. Editor modules,
Qt, coordinators, and delivery-queue modules are excluded and forbidden in a
shipped game.

## Observability

`ObservabilityWatcher` (`observability.py`) records bounded, thread-safe metrics
with free-form string targets (e.g. `app:…`, `ui:…`, `runtime:…`, `render:…`).
See [MCP and Debugging](MCP_AND_DEBUGGING.md).
