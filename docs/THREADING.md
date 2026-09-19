# Threading Model

## The Invariant

**Tk owns widgets. Only the main thread may call any Tk API.**

This is not a style guideline. Tkinter raises errors or silently corrupts state when widgets are touched from background threads. The coordinator architecture enforces this boundary.

## How Work Crosses Threads

```
Main thread                     Worker thread
    |                               |
    | AppCoordinator.run(...)       |
    |------------------------------>|
    |                   task()      |
    |                   result      |
    |<------ deliver(callback) -----|
    |                               |
    | root.after_idle(callback)     |
    |   -> callback runs here       |
    |   -> widget.configure(...)    |
    |   -> UICoordinator.flush()    |
```

The `deliver` function injected into `AppCoordinator` in `EditorWindow` is:

```python
deliver = lambda cb: self.root.after_idle(cb)
```

`after_idle` schedules `cb` to run on the Tk event loop — main thread only.

## Guarantees

| Guarantee | How enforced |
|---|---|
| No widget call from worker | `deliver` wraps every cross-thread result; workers only call `deliver`, never `widget.*` |
| Stale results discarded | Generation counters increment on each new request; old results check current gen before delivering |
| Cancellation safe | `cancel_all()` increments gen; in-flight workers' delivered callbacks are no-ops |
| Shutdown safe | `TimerDelivery.cancel_all()` drains pending timers before `root.destroy()` |

## Sequence: Play button pressed

1. User clicks Play → ButtonCoordinator dispatches `"play"` → `engine.play()` (main thread)
2. Engine deep-copies edit scene via JSON round-trip → stored as `runtime_scene`
3. UICoordinator receives RenderIntent for toolbar and viewport
4. UICoordinator.flush() updates toolbar buttons and viewport canvas — all on main thread

No background threads are involved in the basic play/stop cycle. Background threads are used for file I/O (project load/save) and any future asset operations.

## Sequence: Scene save (background)

1. User triggers save → ButtonCoordinator dispatches `"save_scene"`
2. `EditorWindow._do_save_scene()` calls `coordinator.run("scene:save", task_factory)`
3. Worker thread executes `project.save()` (file I/O)
4. Result delivered via `after_idle` → `ConsolePanel.log("Scene saved")`
5. All widget updates happen on the main thread

## Anti-Patterns (Never Do)

```python
# WRONG — worker directly touching a widget
def worker():
    result = compute()
    self.label.configure(text=result)  # crash or silent corruption

# WRONG — threading.Timer calling into Tk
t = threading.Timer(1.0, lambda: self.widget.config(...))  # WRONG

# CORRECT
coordinator.run("key", lambda: compute(), on_result=lambda r: deliver(lambda: label.config(text=r)))
```

## ComponentRefreshScheduler and Timers

`ComponentRefreshScheduler.collect_due()` is called from `TimerDelivery` callbacks, which always run on the main thread via `root.after(delay, callback)`. The scheduler itself is not thread-safe and must only be used from the main thread.

## ObservabilityWatcher

`ObservabilityWatcher` uses `threading.RLock` internally and is safe to call from any thread. This is the only class in expra_engine designed for concurrent access.
