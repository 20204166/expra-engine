# Expra Engine — Architecture

## Overview

Expra Engine is a game editor and runtime built on the proven System Analyzer coordinator
architecture.  The design separates game state (core), coordination patterns (coordinators),
and Tk presentation (editor) into three distinct layers.

```
┌─────────────────────────────────────────────────────────┐
│  Editor Layer  (Tk / ttkbootstrap)                      │
│  EditorWindow · panels · TkDeliveryQueue · preferences  │
├─────────────────────────────────────────────────────────┤
│  Coordinator Layer  (pure Python, no Tk)                │
│  AppCoordinator · ButtonCoordinator · UICoordinator     │
│  ComponentRefreshScheduler · PendingTransition          │
├─────────────────────────────────────────────────────────┤
│  Engine Core  (pure Python, no Tk)                      │
│  Engine · Project · Scene · Entity · Component          │
└─────────────────────────────────────────────────────────┘
```

---

## Ownership Matrix

| Responsibility                    | Owner                          | Module                              |
|-----------------------------------|--------------------------------|-------------------------------------|
| Game state (scenes, entities)     | Engine                         | `core/engine.py`                    |
| Project / multi-scene container   | Project                        | `core/project.py`                   |
| Scene mutation                    | Scene                          | `core/scene.py`                     |
| Entity lifecycle                  | Entity                         | `core/entity.py`                    |
| Component data                    | Component subclasses           | `core/component.py`                 |
| Background work scheduling        | AppCoordinator                 | `coordinators/app_coordinator.py`   |
| Button / action enable/disable    | ButtonCoordinator              | `coordinators/button_coordinator.py`|
| UI update batching                | UICoordinator                  | `coordinators/ui_coordinator.py`    |
| Refresh interval tracking         | ComponentRefreshScheduler      | `coordinators/scheduler.py`         |
| Play/stop scene isolation         | PendingTransition              | `coordinators/transition.py`        |
| Thread-safe Tk delivery           | TkDeliveryQueue                | `editor/delivery.py`                |
| Delayed Tk callbacks              | TimerDelivery                  | `ui/timer_delivery.py`              |
| Atomic filesystem writes          | persistence                    | `editor/persistence.py`             |
| Single-instance lock              | InstanceLock                   | `editor/instance_lock.py`           |
| User preferences                  | PreferencesStore               | `editor/preferences.py`             |
| Editor app lifecycle              | EditorApplication              | `editor/app.py`                     |
| Tk root + layout                  | EditorWindow                   | `ui/editor_window.py`               |
| Scene hierarchy panel             | HierarchyPanel                 | `ui/hierarchy.py`                   |
| Component inspector panel         | InspectorPanel                 | `ui/inspector.py`                   |
| Scene viewport (canvas)           | ViewportPanel                  | `ui/viewport.py`                    |
| Log / output console              | ConsolePanel                   | `ui/console.py`                     |
| Play/stop/save toolbar            | build_toolbar                  | `ui/toolbar.py`                     |
| Runtime metrics                   | ObservabilityWatcher           | `observability.py`                  |
| Version string                    | __version__                    | `_version.py`                       |
| Release pipeline                  | prepare_build, sync_artifacts  | `_release.py`                       |

---

## Threading Model

### The invariant

**ALL Tk widget mutations must occur on the Tk main thread.**  No exceptions.

Worker threads may never call:
- `widget.configure(...)`
- `widget.after_idle(...)`
- `widget.after(...)`
- Any ttk/Tk API

### Correct cross-thread delivery

```
Worker thread                   Tk main thread (25ms poll)
──────────────                  ──────────────────────────
AppCoordinator._run_worker()
  → result callback
    → deliver(callback)         TkDeliveryQueue._drain()
      → queue.put(callback)  ──►  → callback()
                                    → UICoordinator.request()
                                      → panel.render()
                                        → widget.configure(...)
```

`TkDeliveryQueue.__call__` is the **only** entry point from worker threads.
It puts into a thread-safe `queue.Queue`.  The drain loop runs every 25 ms
on the Tk main thread via `widget.after(25, self._drain)`.

### NEVER do this (anti-pattern)

```python
# WRONG — after_idle called from worker thread
def deliver(callback):
    root.after_idle(callback)  # Tk API from worker thread = undefined behaviour
```

### TimerDelivery

`TimerDelivery` schedules delayed callbacks that run **on the Tk main thread**
(they are created with `master.after(delay, callback)` from main-thread code).
It tracks pending timer IDs and safely cancels them on shutdown.

---

## Coordinator Responsibilities

### AppCoordinator

- Runs background workers in a thread pool
- Coalesces repeated `run("key", ...)` calls (only one active + one pending per key)
- Delivers results through the `deliver=` callable (must be `TkDeliveryQueue`)
- `post_coalesced(key, cb)` — deferred main-thread callbacks, deduplicated per key
- `last_result(key)` — cached last result for each operation key
- `shutdown()` — cancels in-flight work

### ButtonCoordinator

- Maps action names to callables with enabled/disabled state
- `register(name, callback, *, enabled=True)`
- `fire(name)` — calls registered callable if enabled
- `set_enabled(name, enabled)` — controls toolbar button state

### UICoordinator

- Batches UI update intents (begin_batch / end_batch)
- Deduplicates intents by target within a batch (latest generation wins)
- `request(intent, apply_fn)` — apply immediately or queue in a batch
- `invalidate(target, generation)` — mark older intents stale

### ComponentRefreshScheduler

- Tracks per-component refresh intervals (milliseconds)
- `begin(key, now)` → True if the component is due for a refresh
- `finish(key)` → advances the next-due timestamp
- `collect_due()` → returns all keys whose deadline has passed
- `next_deadline(now)` → nearest future deadline for use with `after()`

---

## Play / Stop Runtime Isolation

On **Play**:
1. `Engine.play()` calls `PendingTransition.begin(edit_scene)`
2. The edit scene is JSON-serialised and deserialised (deep copy)
3. The runtime scene is set as the active scene

On **Stop**:
1. `Engine.stop()` discards the runtime scene
2. The original edit scene is restored as active

This means any runtime mutations (physics, scripts) never touch the edit scene.

---

## Editor Layout

```
┌──────────────────── EditorWindow ────────────────────────┐
│  Toolbar (play · pause · stop · new · save · add · del)  │
├──────────┬──────────────────────────┬────────────────────┤
│ Hierarchy│       Viewport           │    Inspector       │
│ (240px)  │    (fill, expand)        │    (280px)         │
│          │                          │                    │
│          │  TkCanvasViewportRenderer│                    │
│          │  (editor preview only,   │                    │
│          │   NOT final renderer)    │                    │
├──────────┴──────────────────────────┴────────────────────┤
│  Console  (160px, fixed)                                  │
└──────────────────────────────────────────────────────────┘
```

The middle section uses `ttkbootstrap.PanedWindow` (horizontal) so all three
panes are user-resizable.

---

## Observability

`ObservabilityWatcher` (in `observability.py`) provides bounded, thread-safe
runtime metrics:

- `record(target, duration, outcome)` — record a completed operation
- `begin(target)` / `finish(token, ...)` — bracket in-flight operations
- `record_event(target, kind)` — count coalesced/stale/rejected events
- `snapshot()` — immutable snapshot of all metrics, safe to read from any thread
- `reset()` — discard all metrics (e.g. on new session)

---

## Packaging Boundary

```
expra-engine wheel
├── expra_engine/           ← all Python source
│   ├── core/               ← Engine, Scene, Entity, Component (no Tk dep)
│   ├── coordinators/       ← pure Python, no Tk dep
│   ├── editor/             ← Tk/persistence/preferences (Tk dep, editor only)
│   ├── ui/                 ← Tk panels and window (Tk dep)
│   ├── observability.py
│   ├── _release.py
│   └── _version.py
└── expra_engine-0.x.x.x.dist-info/
```

`core/` and `coordinators/` must never import `tkinter` or `ttkbootstrap`.
This keeps the engine core importable in headless contexts (tests, export runtime).

---

## Future: Game Export  *(not implemented)*

See `docs/GAME_EXPORT_FUTURE.md` for the full design intent.

Short summary: export = stripped runtime (no Tk) + user project + PyInstaller/Nuitka.
Not implemented until the project format and renderer seam are stabilised.

## Future: Remote Connect  *(not implemented)*

A future remote-connect feature would allow the editor to connect to a running
game instance for live debugging and hot-reload.  Not implemented in this phase.
