# Expra Engine Guide

Canonical, evidence-based documentation for Expra as it exists in the current
repository. These pages live in `docs/guide/` to stay separate from the older
design/planning documents at the `docs/` root.

When a page and the source disagree, trust the source — and fix the page.

Audited against commit `fa774e8` (current `main`).

## Start here

- [Getting Started](GETTING_STARTED.md) — install, launch the editor, first scene/level/world.
- [Architecture](ARCHITECTURE.md) — layers, ownership, threading model.
- [End-to-End Tutorial](END_TO_END_TUTORIAL.md) — build a small complete game.

## Concepts and data model

- [Document Model](DOCUMENT_MODEL.md) — Project / World / Level / Scene / Entity / Component, and the JSON ↔ Protobuf relationship.
- [Projects](PROJECTS.md) — `project.json`, paths, entrypoints.
- [Scenes](SCENES.md) — reusable compositions.
- [Levels](LEVELS.md) — playable places.
- [Worlds](WORLDS.md) — geography, connectivity, travel.
- [World Streaming](WORLD_STREAMING.md) — what streaming does and does **not** do.
- [Scene Instances](SCENE_INSTANCES.md) — instancing, overrides, cycles.

## Building games

- [Entities and Components](ENTITIES_AND_COMPONENTS.md) — complete component reference.
- [Behaviours and Scripting](BEHAVIOURS_AND_SCRIPTING.md) — the Python gameplay API.
- [Resources and Assets](RESOURCES_AND_ASSETS.md) — logical IDs, mounts, resource service.
- [Input](INPUT.md) — keyboard/mouse, InputMap, known limitations.
- [Physics](PHYSICS.md) — colliders, queries, triggers, areas.
- [Camera](CAMERA.md) — Camera2D, coordinates, smoothing, limits.
- [Lighting](LIGHTING.md) — 2D lights, canvas modulation, normal mapping.
- [UI](UI.md) — building HUDs/menus from scenes and components.
- [Audio](AUDIO.md) — 2D listener and stream players.

## Running and shipping

- [Play vs Run Project](PLAY_AND_RUN_PROJECT.md) — the two ways to execute.
- [Editor](EDITOR.md) — the Tk editor, its panels and document modes.
- [Export](EXPORT.md) — the exporter, targets, profiles, verification.
- [Persistence](PERSISTENCE.md) — user data and session/save state.
- [Performance](PERFORMANCE.md) — measured limits and known cost centers.

## Development and reference

- [MCP and Debugging](MCP_AND_DEBUGGING.md) — the MCP tool inventory and observability.
- [Limitations](LIMITATIONS.md) — supported / partial / unsupported, honestly.
- [Troubleshooting](TROUBLESHOOTING.md) — common mistakes and fixes.
- [Glossary](GLOSSARY.md) — terminology.
- [Stale Doc Audit](STALE_DOC_AUDIT.md) — freshness of the older docs at the `docs/` root.

## Older documents (docs/ root, historical)

These remain at the `docs/` root for history and are **not** canonical. See the
[Stale Doc Audit](STALE_DOC_AUDIT.md) for per-file status:

- `../ARCHITECTURE.md` — superseded by [Architecture](ARCHITECTURE.md).
- `../PROJECTS.md` — superseded by [Projects](PROJECTS.md).
- `../SCRIPTING.md` — merged into [Behaviours and Scripting](BEHAVIOURS_AND_SCRIPTING.md).
- `../FILESYSTEM.md` — merged into [Resources and Assets](RESOURCES_AND_ASSETS.md).
- `../DEVELOPMENT_MCP.md` — merged into [MCP and Debugging](MCP_AND_DEBUGGING.md).
- `../PERFORMANCE_BASELINE.md` — merged into [Performance](PERFORMANCE.md).
- `../THREADING.md` — retained (threading model, still accurate).
- `../GAME_UI_FUTURE.md`, `../GAME_EXPORT_FUTURE.md` — design intent, not current.
- `../*_INTEGRATION_MAP.md`, `../POLISH_EXTRACTION_MAP.md`, `../SPACE_PONG_*.md` — project-evaluation notes.
