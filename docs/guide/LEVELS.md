# Levels

A **Level** is a playable place: a `Scene` plus `LevelMetadata`. `Level` is a
subclass of `Scene`, so everything a Scene can do, a Level can do — plus
playable-place metadata.

## What a Level is

```python
from expra_engine.core.scene import Level
from expra_engine.core.scene.level import LevelMetadata

level = Level("Intro", level_metadata=LevelMetadata(
    display_name="Intro Level",
    world_bounds=(-50.0, -30.0, 50.0, 30.0),
    spawn_entity_id="player",
    default_camera_id="main_camera",
))
```

`LevelMetadata` (frozen dataclass):

| Field | Type | Purpose |
|---|---|---|
| `display_name` | `str \| None` | human-readable name |
| `world_bounds` | `(l, b, r, t) \| None` | level bounds |
| `spawn_entity_id` | `str \| None` | spawn point entity |
| `default_camera_id` | `str \| None` | default camera entity |
| `tags` | `tuple[str, …]` | |

Whole-level semantics live in metadata only; enemies, walls, triggers, and NPCs
are ordinary entities.

## Level vs Scene

| | Scene | Level |
|---|---|---|
| `document_kind` | `"scene"` | `"level"` |
| playable place | — | yes (has bounds/spawn/camera) |
| reusable composition | yes | less common |
| world-integrated | instantiated manually | via `LevelDescriptor` |

## What belongs in a Level

- environment geometry, local NPCs, local enemies, local triggers;
- local Scene Instances;
- entrance/exit `LevelAnchorComponent`s (see [Worlds](WORLDS.md)).

## What does NOT belong in a Level

- the persistent player (that's a `WorldPersistentActorComponent`);
- world geography/connectivity (that's the World);
- global session state (that's `WorldSessionStateComponent`).

## Level coordinates vs world placement

A Level's entities live in the Level's own coordinate space. When a Level is
placed in a World, its `LevelDescriptor.origin` offsets it into world space;
the streaming system applies that offset during materialization. The Level
document itself does not know where it is in the World.

## Anchors

`LevelAnchorComponent` (type `"level_anchor"`) marks an entity as an
entrance/exit portal. `Level.find_anchor(anchor_id)` looks one up;
`Level.validate_anchors()` checks for duplicate anchor ids. See
[Worlds](WORLDS.md) for how anchors drive travel.
