# Intra-Level Chunk Streaming — Design Notes (not yet planned)

**Status:** Pre-design notes. No implementation planned for the current cycle.
See `2026-09-26-first-class-world-streaming.md` for the shipped inter-Level
streaming design.

---

## What this is not

The current World streaming system (shipped 2026-09-26) streams **whole
Levels** in and out of memory as the player moves through a World graph. Each
Level is an indivisible unit: one `.level.pb` file, one Scene in memory.

Intra-Level chunk streaming means dividing a single Level into **spatial
sub-regions (chunks)** so that only the fraction of the Level near the player
is materialized into the runtime Scene at any given time. This is needed only
when a Level is too large to hold fully in memory.

---

## When it becomes relevant

The current Level design handles large scenes well because:
- Entities outside the camera frustum are never rendered.
- Physics is cheap when inactive entities have no colliders.
- The document codec is fast (PB decode is O(n) in entity count).

Chunk streaming only becomes necessary when a single Level has enough entities
that the **initial load** or **full in-memory representation** causes a
perceptible freeze or exceeds available RAM. This threshold is far above what
any current Expra project approaches.

Signal to revisit: when `performance_probe(action="document_load")` on a
real Level reports first-load latency > 300 ms or when RAM profiling shows
the materialized Scene consuming > 200 MB.

---

## Candidate design

A possible intra-Level chunk model, for future reference only:

### 1. Chunk regions in the Level document

A `ChunkDescriptor` (analogous to `LevelDescriptor` in a World) would mark a
rectangular world-space region in the Level and point to a sub-document:

```
LevelChunkDescriptor:
  chunk_id:         str
  bounds:           (x, y, w, h) in world-space
  resource_path:    "levels/chunks/forest_north.chunk.pb"
  always_loaded:    bool  (e.g. spawn-region)
  priority:         int
```

### 2. Streaming anchor in the Level

The Level's own `StreamingAnchorComponent` entities would serve as the
streaming position source, the same way they do for World-level residency
decisions today.

### 3. Chunk codec

A `.chunk.pb` file is a subset of a Level: a list of Entity/Component trees
with their world-space transforms already baked. The Level's `Scene` acts as
the "runtime view" — chunks are **merged into it** on load and **pruned from
it** on unload. Pruning must not destroy authored entities the chunk did not
own.

### 4. Ownership and authority

- A Level entity either lives in the main `.level.pb` (always resident) or
  exactly one `.chunk.pb`.
- An entity cannot span chunk boundaries.
- The chunk system is owned by a `LevelChunkSystem` sibling of
  `WorldStreamingSystem`. They are independent; a World can contain chunked
  and un-chunked Levels.
- Persistence (UserDataStore) treats a chunk entity's save key as
  `{level_id}/{chunk_id}/{entity_id}` to avoid collisions across loads.

### 5. Editor authoring

The editor workflow would need:
- A "Mark as chunk" action on a selection of entities → writes them to a
  new `.chunk.pb` and replaces them in the main Level with invisible anchor
  entities.
- A "Merge chunk" action → opposite direction.
- Viewport rendering with chunk region outlines (like the current Level
  origin/bounds overlays in the World viewport).

This is non-trivial editor work. It should not be started until the runtime
architecture above is proven with at least a synthetic benchmark.

---

## Deferred decisions

1. **Chunk overlap**: allowing the same entity to appear in overlapping chunks
   simplifies authoring (no hard cell boundaries) but complicates ownership
   and pruning. Avoid until a concrete need arises.
2. **Dynamic chunk generation**: procedural or streaming-service-backed
   chunks (e.g. tiles fetched from a server). Out of scope; the Filesystem/
   ResourceService abstraction already supports remote providers, but the
   Level chunk system should first be validated on static assets.
3. **Serialization format**: `.chunk.pb` re-uses the Level protobuf schema
   with `document_kind = CHUNK` (a new value, not yet added). The field-number
   stability guarantee in `schemas/level.proto` already reserves this space.

---

## References

- `src/expra_engine/core/world.py` — `LevelDescriptor`, `WorldStreamingSettings`
- `src/expra_engine/runtime/world_streaming.py` — `WorldStreamingSystem`,
  `LevelResidencyManager`
- `src/expra_engine/runtime/world_policy.py` — `WorldStreamingPolicy`,
  `StreamingDecision`
- `docs/plans/2026-09-26-first-class-world-streaming.md` — shipped design
- `docs/specs/2026-09-26-world-streaming-design.md` — spec
