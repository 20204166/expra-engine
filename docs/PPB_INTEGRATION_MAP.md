# PPB to Expra Integration Map

Audited read-only sources under `/home/btn17/Downloads/pursuedpybear-canon`:
`src/ppb/engine.py`, `events.py`, `systemslib.py`, `scenes.py`, `gomlib.py`,
input systems, and engine/event tests.

| PPB lesson | Expra owner | Decision |
|---|---|---|
| One FIFO queue with deferred nested signalling | `runtime.EventQueue` | Preserve |
| `on_<event>` naming and signature validation | `EventQueue` | Reuse |
| Scene lifecycle notifications | `Engine` and `BehaviourSystem` | Reuse |
| Flush stale events before transitions | `Engine.push/pop/replace_scene` | Preserve |
| Explicit system startup/shutdown | `RuntimeSystem` and one `BehaviourSystem` | Adapt |
| Targeted weak delivery | Explicit Expra targets | Do not copy hidden weak ownership |
| SDL input and `Children` inheritance | `InputMap`, `Scene`, `Entity` | Reject coupling |
| Unstable system set iteration | Ordered Expra system list | Strengthen |

Tests carry forward invalid handler signatures, TypeError inside valid handlers,
deferred events, queue flushing, startup rollback, scene ownership, mutation
during dispatch, and partial teardown. Expra remains the runtime-loop owner and
does not make each Behaviour a PPB-style System.
