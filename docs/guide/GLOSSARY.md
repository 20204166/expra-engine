# Glossary

- **Project** — the whole game: `project.json` + document registries + assets +
  scripts + entrypoint.
- **World** — geography, connectivity, residency, and travel between Levels.
- **Level** — a playable place: a `Scene` plus `LevelMetadata`.
- **Scene** — a reusable composition of entities.
- **Scene Instance** — an entity that materializes a copy of a source Scene's
  hierarchy (via `SceneInstanceComponent`).
- **Entity** — a named object with components, tags, and a parent.
- **Component** — typed data attached to an entity (e.g. `transform`, `sprite`).
- **Behaviour** — a gameplay script subclass attached via `ScriptComponent`.
- **Runtime** — the headless engine loop (clock, event queue, systems, renderer).
- **Document** — a serializable Scene/Level/World.
- **PB** — Protobuf (`protobuf`), the canonical persistent document format
  (`.scene.pb`, `.level.pb`, `.world.pb`).
- **JSON** — the legacy human-readable document representation (read-only import).
- **LevelDescriptor** — a World entry naming a Level, its origin, bounds, and
  streaming flags.
- **WorldConnection** — a directed edge between a source anchor and a
  destination anchor.
- **TransitionMode** — `seamless` / `fade` / `instant` / `loading`.
- **StreamingAnchor** — `StreamingAnchorComponent`; drives Level residency.
- **LevelAnchor** — `LevelAnchorComponent`; an entrance/exit portal.
- **Persistent Actor** — `WorldPersistentActorComponent`; survives Level travel.
- **Loaded Level** — data resident but not active.
- **Active Level** — entities in the world scene.
- **Primary Level** — the initial/entry Level (or the one the primary anchor is in).
- **Transition** — moving a persistent actor between Levels.
- **Resource** — an asset addressed by a logical ID (`assets://…`).
- **Authoring** — editing documents (editor / CLI).
- **Session** — state preserved across Level travel within one run.
- **Save** — user data persisted across launches (`UserDataStore`).
