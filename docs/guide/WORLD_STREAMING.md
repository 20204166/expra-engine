# World Streaming

`WorldStreamingSystem` (`runtime/world_streaming.py`) is the runtime owner for
World (multi-Level) gameplay. This page states exactly what it does and what it
does not do, from the source.

## What World streaming DOES

- **Loads Level content on demand** — Levels are loaded and materialized off the
  owner thread via a `ThreadPoolExecutor` (size = `max_concurrent_loads`,
  default 2). Completions arrive on a `queue.SimpleQueue`.
- **Tracks residency** — each Level's lifecycle state is tracked by
  `LevelResidencyManager`.
- **Distinguishes loaded from active** — see [Loaded vs active](#loaded-vs-active).
- **Reconciles a streaming policy** — `_reconcile_streaming_policy()` decides
  which Levels should be active/resident/preloaded from active streaming
  anchors, the connection graph (preload/unload distances), pinned/always-loaded
  Levels, and handover holds.
- **Traverses seamless connections automatically** — when a persistent actor
  crosses a portal trigger, a transition is initiated.
- **Hands persistent actors over** — persistent actors are torn out of Level
  ownership and placed directly in the World aggregate scene.
- **Captures/restores session state** — `WorldSessionState` handles opt-in
  entity state across unload/reload.
- **Tracks camera context** — which Level the camera is inside.
- **Unloads according to policy** — Levels beyond `unload_distance` (and not
  pinned/always-loaded) are unloaded.
- **Supports transition modes** — `seamless` / `fade` / `instant` / `loading`
  (see [Transition modes](#transition-modes)).

## What World streaming DOES NOT do

- It does **not** turn every Level into a chunk or stream individual entities;
  Levels load/unload atomically.
- It does **not** load all Levels at once.
- It does **not** infer connections from physical proximity — connections are
  authored.
- It does **not** make every actor persistent — only entities with
  `WorldPersistentActorComponent`.
- It does **not** auto-save game state on unload — `save_session()` is explicit.
- It does **not** make the camera equal to the streaming anchor — camera context
  is separate from residency anchors.
- It does **not** replace Scene Instances.
- It does **not** make the World a giant entity tree.
- It does **not** automatically create entrances/exits — anchors are authored.
- It does **not** preserve arbitrary runtime state — only persistent-actor
  transforms and `WorldSessionStateComponent` values.
- It does **not** render a visual fade itself (see below).
- It does **not** handle networking/replication.
- It does **not** perform GPU occlusion or culling.

## Loaded vs active

`LevelResidencyState` (`runtime/world_policy.py`):

| State | Meaning |
|---|---|
| `UNLOADED` | no data resident |
| `QUEUED` | load requested, waiting for a worker slot |
| `LOADING` | load in progress |
| `LOADED` | data resident, entities **not** in the world scene |
| `ACTIVE` | entities transferred into the runtime scene |
| `DORMANT` | was active; entities returned to the Level wrapper |
| `FAILED` | load/activation failed |
| `CANCELLED` | load cancelled |

**`loaded != active`**: a `LOADED` Level has its data in memory but does not
participate in gameplay. An `ACTIVE` Level has its entities in the world scene.
`loaded_levels()` returns LOADED|ACTIVE|DORMANT; `active_levels()` returns only
ACTIVE.

## Streaming anchors

`StreamingAnchorComponent` (type `"streaming_anchor"`) nominates an entity as a
**residency anchor**: its position determines which Level it is inside, and that
Level must stay active. `World.primary_anchor_id` names the primary
player/camera anchor. The primary anchor must be on a persistent actor.

This is **different** from `LevelAnchorComponent`, which marks an
**entrance/exit portal** — "where is the door to the next Level?" vs "what Level
is the player in now?"

## Persistent actors

`WorldPersistentActorComponent` (type `"world_persistent_actor"`) marks a Level
**root** entity as persistent across travel.

- `persistent_id` must be unique across the whole World.
- The entity and its entire descendant subtree are transferred to the World
  aggregate scene on activation.
- **What persists**: `TransformComponent` and `WorldSessionStateComponent`
  values.
- **What does not persist**: everything else, unless explicitly captured via
  `WorldSessionStateComponent`.
- Must be a Level root (cross-owner parenting is unsupported).
- At startup, if it is the primary anchor and an initial entrance exists, its
  position is set to that entrance's world position.

Common mistakes: a persistent player with Level-owned attack hitboxes; duplicate
`persistent_id`s; making every enemy persistent; relying on entity `name`.

## Transition modes

| Mode | Runtime behaviour |
|---|---|
| `seamless` | anchors must be within ~0.01 units; actor keeps its position; camera context unchanged. |
| `fade` | multi-phase sequence (PREPARING→FADING_OUT→SWITCHING→FADING_IN→COMPLETE); computes an `alpha` 0→1→0 (default `fade_duration` 0.2 s). The **alpha is surfaced to the renderer** — the transition controller does not draw a fade quad. Actor is placed at the destination anchor; camera context updates. |
| `instant` | straight to SWITCHING; same commit behaviour as `fade` for position/camera. |
| `loading` | **behaves identically to `instant`** at the controller level (the enum exists but no distinct path). |

## Session state

`WorldSessionStateComponent` (type `"world_session_state"`) holds a
JSON-serializable `values` dict. `WorldSessionState.capture_level()` /
`restore_level()` snapshot and restore these values (plus transforms for
persistent actors) across unload/reload. Persistent-actor subtree entities are
excluded from Level session capture (they're handled separately).
