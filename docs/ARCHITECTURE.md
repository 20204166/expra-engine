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
│  Runtime Layer  (pure Python, no Tk)                     │
│  EventQueue · RuntimeClock · RuntimeSystem · scene stack │
├─────────────────────────────────────────────────────────┤
│  Engine Core  (pure Python, no Tk)                      │
│  Engine · Project · Scene · Entity · Component · Camera2D│
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
| Refresh interval tracking         | ComponentRefreshScheduler      | `coordinators/refresh_scheduler.py`|
| Play/stop scene isolation         | Engine                         | `core/engine.py`                    |
| Delayed/latest-wins UI transition | PendingTransition              | `coordinators/transition.py`        |
| Runtime event dispatch            | EventQueue                     | `runtime/event_queue.py`            |
| Fixed-step runtime clock          | RuntimeClock                   | `runtime/clock.py`                  |
| Runtime subsystem lifecycle       | RuntimeSystem                  | `runtime/system.py`                 |
| Runtime scene stack               | Engine                         | `core/engine.py`                    |
| Camera coordinate transforms      | Camera2D                       | `core/camera.py`                    |
| Entity hierarchy, tags, queries   | Scene / Entity                 | `core/scene.py`, `core/entity.py`   |
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
- `dispatch(action_id)` — calls the registered callable if enabled
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

## Runtime Layer

The runtime layer is headless and is driven by the caller through
`Engine.tick()` or `Engine.loop_once()`. `EventQueue` provides FIFO signal and
publish dispatch. `RuntimeClock` converts `Idle` events into fixed-step
`Update` events, and `RuntimeSystem` is the lifecycle seam for pluggable
subsystems. The runtime scene stack lives on `Engine`; it is separate from the
editor scene and dispatches scene lifecycle events on push, pop, and replace.

`StartScene`, `StopScene`, `ReplaceScene`, and `Quit` are actionable queued
requests. `Engine` handles them through the event queue and applies the
corresponding scene-stack operation. `SceneStarted`, `SceneStopped`,
`ScenePaused`, and `SceneContinued` are lifecycle notifications.

### Future game UI boundary

The editor's Tk UI is not the runtime UI. Shared renderer-neutral design
concepts live in `expra_engine.design`; the Tk adapter in `ui/styles.py` is
editor-only. A future game UI package may provide `GameCanvas`, `UIElement`,
`Panel`, `Label`, `Button`, `Image`, `ProgressBar`, `ScrollView`, and
`AnchorLayout`/`Row`/`Column`/`Stack`, but it must render through an explicit
backend rather than importing Tk. The boundary is intended to support HUDs,
menus, inventories, dialogue, touch controls, safe areas, DPI scaling, and
multiple aspect ratios without coupling shipped games to editor widgets. See
`docs/GAME_UI_FUTURE.md`; this pass does not implement that runtime system.

## Play / Stop Runtime Isolation

On **Play**:
1. `Engine.play()` JSON-serialises and deserialises the edit scene (deep copy)
2. The copied scene is placed on the runtime scene stack
3. The edit scene remains owned by the editor and is never placed on that stack

On **Stop**:
1. `Engine.stop()` discards the runtime scene stack
2. The original edit scene remains active and is restored for editing

This means any runtime mutations never touch the edit scene. `PendingTransition`
does not own this isolation; it remains a UI timing primitive that cancels and
supersedes delayed callbacks.

## Core Scene Data

`Entity` supports parent relationships and tags. `Scene` owns hierarchy
operations and query methods for tags, components, and entity types. These are
data-model facilities used by both the editor and headless runtime; they do not
introduce renderer, input, assets, physics, animation, or audio systems.

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

## Wheel Build Automation

`scripts/build-wheel.sh` is the Expra-native release entry point. It calls
`prepare-build` before building, so source changes automatically select the
next independent Expra version rather than reusing System Analyzer's version.
After the wheel is built it refreshes `dist/SHA256SUMS` and runs the wheel
boundary verifier. If the build fails, the source version file is restored.
Expra-specific thresholds classify shell/core structure as `minor`, while
editor panels, styles, design tokens, and runtime feature surfaces classify as
`feature`; routine internals remain `patch`.
The script builds but does not install or silently update a user's editor.
`scripts/install-user.sh` is the explicit installation path modeled after the
System Analyzer installer: it selects the base system interpreter rather than
the repository `.venv`, verifies the wheel, installs it into the user site (or
system site with `--system`), and confirms the installed version. There is no
silent background updater.

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
│   ├── _version.py
│   └── py.typed             ← required package data
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
