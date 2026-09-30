# Threading Model

## The invariant

**Qt widgets are owned by the Qt GUI thread.** Worker threads must not create,
mutate, inspect, or destroy widgets. Shared editor state and engine/runtime
objects keep their existing ownership; this document describes UI delivery,
not a redesign of `AppCoordinator`.

## Worker-to-UI delivery

The Qt editor injects `QtDeliveryQueue` into `AppCoordinator` as its `deliver`
callable:

```text
Qt GUI thread                         Worker thread
--------------                        -------------
AppCoordinator.run(...)  -----------> task()
                                      result
UICoordinator <- queued callback <--- deliver(callback)
  -> panel update on Qt GUI thread
```

Workers enqueue callbacks only. `QtDeliveryQueue` drains on the GUI thread via
Qt timers, with bounded work per drain. It closes with its owning window,
discards pending callbacks on shutdown, and performs timer operations on the
timer's owning thread. Do not call widget methods directly from worker code.

## Guarantees and limits

| Guarantee | Owner |
|---|---|
| Worker results are applied on the GUI thread | `QtDeliveryQueue` |
| Stale UI intents are rejected | `UICoordinator` |
| Worker cancellation/coalescing lifecycle | `AppCoordinator` |
| Timer callback cancellation and close handling | `QtTimerDelivery` |
| Engine Play/Stop state isolation | `Engine` |

The coordinator's threading model is intentionally unchanged by the Tk-removal
cleanup. The Qt queue is the GUI delivery adapter; it does not own game/runtime
timing.

## Play and runtime preview

Play/Stop remains engine-owned. Qt timer delivery may schedule editor preview
work, but `Engine.tick()` and game runtime timing are not moved into Qt. Runtime
failures are handled by the existing editor workflow and lifecycle tests.

## Shutdown

Close the editor through the window's normal close handler. The Qt delivery
queue closes before its shell is destroyed so later worker completion cannot
reach destroyed widgets. Timers and queued callbacks are cancelled or ignored
according to their existing owners. Do not use `threading.Timer` to call into
Qt widgets.

## Observability

`ObservabilityWatcher` is thread-safe and remains the shared source for runtime,
coordinator, and editor metrics. See the [architecture guide](guide/ARCHITECTURE.md)
for ownership boundaries.
