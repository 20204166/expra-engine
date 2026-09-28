# Worlds

A **World** describes geography and connectivity between Levels: which Levels
exist, where they are placed, how they connect, and how they are streamed. It
owns no entity graph.

## The World document

`World` (`core/world.py`) is a frozen dataclass:

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `world_id` | `str` | required |
| `levels` | `tuple[LevelDescriptor, …]` | `()` |
| `connections` | `tuple[WorldConnection, …]` | `()` |
| `primary_anchor_id` | `str \| None` | `None` |
| `initial_level_id` | `str \| None` | `None` |
| `initial_entrance_id` | `str \| None` | `None` |
| `streaming` | `WorldStreamingSettings` | defaults |
| `metadata` | `dict` | `{}` |

## LevelDescriptor

```python
@dataclass(frozen=True)
class LevelDescriptor:
    instance_id: str                        # unique within the World
    resource_path: str                      # must end in .level.pb
    origin: tuple[float, float] = (0.0, 0.0)
    bounds: tuple[float, float, float, float] | None = None
    tags: tuple[str, ...] = ()              # unique
    always_loaded: bool = False
    priority: int = 0
    metadata: dict = {}
```

`bounds` width/height must be positive. `origin` is the world-space placement of
the Level's local origin.

## WorldConnection

```python
@dataclass(frozen=True)
class WorldConnection:
    connection_id: str
    source_level_id: str
    source_anchor_id: str        # an exit/anchor in the source Level
    destination_level_id: str
    destination_anchor_id: str   # an entrance/anchor in the destination Level
    bidirectional: bool = False
    transition: TransitionMode = TransitionMode.SEAMLESS
    preload_distance: float = 24.0
    unload_distance: float = 48.0   # must be > preload_distance
```

Bidirectional connections are expanded into forward + reverse edges at load.

## TransitionMode

`seamless` (default) · `fade` · `instant` · `loading`. See
[World Streaming](WORLD_STREAMING.md#transition-modes) for exact runtime
behaviour — including which of these actually render a fade.

## WorldStreamingSettings

```python
@dataclass(frozen=True)
class WorldStreamingSettings:
    max_concurrent_loads: int = 2
    max_loaded_levels: int = 8
```

Both must be positive ints.

## World creation tutorial

1. **Create Level A.** New Level → add entities → add an exit
   `LevelAnchorComponent` with `kind="exit"` and a unique `anchor_id`.
2. **Create Level B.** Add an entrance `LevelAnchorComponent` with
   `kind="entrance"` and a unique `anchor_id`.
3. **Create a World** (File → New → World). It starts empty.
4. **Add Level descriptors** (World toolbar "Add Level", or drag a `.level.pb`
   asset onto the world viewport). Each gets a unique `instance_id` and an
   `origin`.
5. **Set placement** — adjust each descriptor's `origin`/`bounds` in the
   inspector.
6. **Create a connection** — pick source level + source anchor (exit), then
   destination level + destination anchor (entrance). Choose a transition mode.
   For `seamless`, the two anchor positions must be within ~0.01 units.
7. **Set the initial level** — the level the game starts in.
8. **(Optional) set `primary_anchor_id`** — the streaming anchor that follows
   the player.
9. **(Optional) mark the player `WorldPersistentActorComponent`** so it survives
   travel.
10. **Register the World** in the project and **set it as the entrypoint**.
11. **Run Project** to play from the World.
12. **Travel** by walking the persistent actor through the exit anchor.

## World travel semantics

Travel is authored, not inferred: you explicitly create connections between
named anchors. Physical proximity alone does not create a connection.
