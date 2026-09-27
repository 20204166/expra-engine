# World Streaming Demo

A minimal two-level project that demonstrates Expra's World streaming system:
two rooms (Town and Cave) connected by FADE transitions.

## Running

```
python -m examples.world_streaming
```

The first run generates `levels/town.level.pb`, `levels/cave.level.pb`, and
`worlds/overworld.world.pb` from code. Subsequent runs use the saved files
directly.

## Controls

| Key | Action |
|-----|--------|
| A / ← | Move left |
| D / → | Move right |

Walk the blue player square to the yellow gate at either edge to cross to the
other room.

## Structure

```
world_streaming/
├── __main__.py                  # Bootstrap + launcher (run_project)
├── worlds/
│   └── overworld.world.pb       # World graph: Town + Cave + 2 connections
├── levels/
│   ├── town.level.pb            # Outdoor room (green)
│   └── cave.level.pb            # Underground room (dark)
└── scripts/
    └── world_streaming_behaviour.py  # PlayerBehaviour: move + travel()
```

The `PlayerBehaviour` calls `engine.world_streaming_system.travel(connection_id)`
when the player reaches an edge. The `WorldStreamingSystem` handles the FADE
transition, level load/unload, and scene swap.

## Key APIs

```python
# Trigger a level transition from a Behaviour script:
wss = self.engine.world_streaming_system
wss.travel("town_to_cave")          # connection_id from the World document

# Inspect the World at runtime:
world = wss.world                   # expra_engine.core.world.World
print(world.connections_from("town"))
```

## Extending

- **Add a third room:** create a new Level, add a new `LevelDescriptor` to the
  World, and add `WorldConnection` entries in `__main__.py._bootstrap()`.
- **Persistent actor:** wrap the player in a `WorldPersistentActorComponent` so
  it carries its runtime transform across transitions instead of snapping to the
  authored position.
- **Seamless streaming:** change `transition=TransitionMode.SEAMLESS` and set
  `preload_distance` so the engine pre-loads the neighbour level before the
  player actually crosses.
