# World Documents and Connected-Level Streaming

**Status:** Proposed architecture for this implementation. **Base:** `9cacad4e857ccf04f5f9ba6e20cf2e10b4f4743c`.

## Context and current capability audit

The old assessment is still accurate at this baseline. Expra has authored `Scene`/`Level` documents, Level metadata, deterministic protobuf, SceneInstance resolution, per-project resource services/cache, bounded `AppCoordinator` workers with cancellation/generation checks and injected delivery, `RuntimeSystem`, Pygame runtime, 2D camera, entity hierarchy, dialogue/audio/animation/physics primitives, confined atomic `UserDataStore`, editor workflow for opening `.level.pb`, and exporter. It still has no World document/graph, anchor/connection model, multi-Level residency owner, World streaming policy, internal tilemap renderer, or World authoring view. `TileMap` and `Grid2D` are bounded data utilities; `TileMap` has no renderer/authoring references. Export currently copies project files rather than resolving a World-specific dependency closure.

Baseline: source imports from this working tree; Python 3.12.3, Pygame 2.6.1, Tk 8.6, Xvfb and pytest available. The configured full test profile timed out without structured totals. Focused `test_project_workflow.py`: 23 passed. `test_multi_level_workflow.py` timed out in the MCP check. The untracked `examples/The_Second_Mark_Story_and_Game_Bible.md` is user work and remains untouched. No source edits existed at audit start.

The connected GitHub MCP is not exposed here; `gh` is unavailable and the REST request returned 403. Read-only `git ls-remote origin refs/heads/main` returned the same SHA as local HEAD. This is explicitly a fallback, not a GitHub-MCP inspection. Reference roots report no Git revisions.

## Ownership / reuse decisions

| Responsibility | Current owner / alternate | Decision |
|---|---|---|
| Scene/Level documents, entity graph | `core.scene.Scene`, `Level`, `document_codec`, `Project` | Extend typed document dispatch; retain Level as ordinary Scene subtype. |
| Project resource bytes/cache/dependencies | `ResourceService`, `ResourceResolver`, `ResourceCache`, `DependencyGraph` | Reuse for resource dependencies; add pure, non-publishing project-document reads for workers. |
| Background work | `AppCoordinator`; editor `TkDeliveryQueue` | Reuse bounded worker/generation lessons, never its default synchronous delivery for runtime mutation; publish completion to Engine owner thread. |
| Runtime lifecycle/events | `Engine`, `RuntimeSystem`, `EventQueue`, `BehaviourSystem` | Extend existing owners for multiple active Level entities and lifecycle; no parallel entity/system/renderer. |
| Physics/audio/animation/render | `PhysicsWorld2D`, `Audio2DSystem`, `AnimatedSpriteSystem`, `extract_render_frame` | Extend canonical systems to observe the active World aggregate; unloaded entities must leave every system. |
| Editor | `EditorWindow`, `ProjectWorkflow`, Asset Browser, Hierarchy, Inspector, Viewport | Extend current application with descriptor-level World mode; unloaded entity graphs remain unloaded. |
| Save data | `UserDataStore` + atomic persistence | Keep authored protobuf, live session deltas, and opt-in save data separate. |
| Tile/chunk helpers | `Grid2D`, `TileMap` | Keep separate; World streaming loads whole Levels first. Internal Level chunks remain a future interface. |

## Reference extraction matrix

| Concern | Godot | Ursina | PPB | MiniPyEngine | Expra decision |
|---|---|---|---|---|---|
| Scene ownership/lifetime | SceneTree owns nodes; PackedScene instantiates; change is main-thread and deferred through tree lifecycle. | `Scene` owns entity list; `enabled` gates visibility/update; `clear()` destroys non-eternal entities. | Engine owns scene stack; push/pop are explicit and lifecycle events have defined order. | `GameObjects` is a simple explicit list used by draw/update/collision; no World graph. | WorldRuntime owns Level instances; lifecycle actions remain Engine-thread operations. |
| Background loading | ResourceLoader has status/result APIs, shared tasks/cache, and references; threaded result retrieval can block, so poll readiness. | Resource helpers load assets; inspected terrain/chunk samples are not a Level streaming owner. | Asset loading system exists; loading-screen example is a presentation pattern, not World streaming. | No mature background scene loading found. | Fixed worker budget, immutable load result, owner-thread publication, generation-checked activation. |
| Activity/physics/render | Node process mode and collision disable semantics are explicit. | Entity enable/disable gates code/visibility and has hooks. | Scene stack exposes top scene; lifecycle events are deterministic. | Update/draw loops traverse all object list entries. | Loaded != active; inactive levels excluded from all runtime systems. |
| Persistence/streaming | Resource cache/ref-count and PackedScene are distinct from mutable gameplay state. | Destroy/recreate is simple but no generic save-delta contract. | No mature World streaming system identified. | No stream/chunk lifecycle or durable session model identified. | Authored Level immutable; runtime deltas live in World session; UserDataStore save is explicit. |
| Coordination | Thread-safe resource loading, with main-thread scene-tree mutation. | Not a concurrency reference. | FIFO scene lifecycle. | Not a concurrency reference. | `/exp` AppCoordinator contributes key coalescing, bounded workers, cooperative cancellation, generations and injected delivery only; no Tk dependency. |

Reference files inspected: Godot `ResourceLoader.xml`, `resource_loader.cpp`, `SceneTree.xml/cpp`, `Node.xml`; Ursina `entity.py`, `scene.py`, `scripts/chunk_mesh.py`; PPB `engine.py`, `events.py`, loading-screen example; MiniPyEngine `GameObjects.py`, `GameObjectBase.py`, engine/map files; `/exp` `maintenance/components/coordinator.py`. Godot/Ursina/MiniPy are MIT; PPB uses Artistic License 2.0; `/exp` has no discoverable license in the reference root. No implementation was copied; only behavioral principles are used.

## Decisions

1. `World` is a metadata document (`*.world.pb`) containing identity, streaming defaults, deterministic initial Level/entrance, descriptors, placements, and directed connections. It does not load all Level documents on open.
2. A descriptor has a stable instance ID independent of the source path, Level resource path, Level-local origin/bounds, tags, priority, and residency flags. Duplicate source Levels are allowed only with distinct instance IDs and namespaced runtime entity identity.
3. Named `LevelAnchorComponent` markers belong to ordinary Level entities; World connections reference source/destination descriptor IDs and anchor IDs. Connections are directed unless explicitly bidirectional. Doors/interiors and spatial neighbors share this graph.
4. Level transforms are Level-local. Descriptor origin is composed at a synthetic per-instance root so render/physics/audio consume one consistent World pose. The persistent World scene is an aggregate view over ordinary Expra entities, not another entity model.
5. Residency states are explicit: `UNLOADED`, `QUEUED`, `LOADING`, `LOADED`, `ACTIVE`, `DORMANT`, `FAILED`, `CANCELLED`. Only active entities update, render, collide, animate, emit local audio, and receive entity events. Multiple Levels may be active during seamless overlap.
6. Default physically adjacent connection mode is `SEAMLESS`; other supported modes are `FADE`, `INSTANT`, and `LOADING`. Destination load/restore/activation commits before source deactivation or actor relocation. Failed destinations leave the current Level usable.
7. Streaming anchors are generic and multiple. Desired residency is their union plus pinned/always-loaded descriptors. Preload starts inside a configurable approach distance; eviction requires a larger exit distance or grace, deterministic priority/ID ordering, and bounded concurrent loads/resident Levels.
8. Workers read/decode/build data only. Engine thread restores state, changes runtime registries, activates, transitions, and unloads. Each request is fenced by World identity, descriptor identity, and monotonically increasing generation. Uncancellable reads may finish, but stale results cannot publish.
9. Persistent actors live in a World-owned persistent entity collection and are moved, not recreated, across Level boundaries. Cross-Level parenting remains forbidden; references to unloaded entities resolve absent rather than retaining object pointers.
10. Before unload, capture only entity deltas against resolved authored Level defaults plus deleted IDs. Spawned-entity persistence is deferred unless stable spawn identity is implemented in the first slice. Restore deltas before behavior start. Save/load World session is explicit, versioned, and stored through injected `UserDataStore`; no runtime state is written to `.level.pb` or `.world.pb`.
11. Run Project continues to use the configured script entrypoint; `project_runner` loads the document entrypoint and selects Scene/Level or World. Existing Scene/Level startup and Level-only Play remain compatible. Export packages project documents via the existing project-file traversal; validate exported World references and runtime closure without adding a second scanner.
12. Editor adds World document workflow and descriptor/connection presentation to the current EditorWindow. It must not materialize all Level entity trees. World viewport overlays are editor-only. Internal tile/entity chunk streaming is out of scope for this first implementation.

## Failure / observability contract

Document and graph validation reject duplicate IDs, unsafe paths, missing Levels/anchors, non-finite placements, invalid transitions/policies, and invalid initial targets before runtime. Failed reads enter `FAILED` with bounded diagnostics and explicit retry. Capture failure retains the resident Level. Metrics use stable bounded target names, never Level IDs/paths. Snapshots explain residency reasons and pending requests. Stop/World switch invalidates generations, cancels queued work, deactivates all active Levels, shuts down workers without late mutation, and preserves the edit document.

## Rejected approaches

- One grid cell per Level: destroys authored district-level semantics and makes graph/asset authoring needlessly huge.
- TileMap-only chunks or one giant Scene: conflicts with the ordinary Level document boundary and future internal-chunk separation.
- A second renderer/entity model/loader or copying Godot/PPB architecture: duplicates canonical Expra owners and introduces incompatible lifecycle semantics.
- Worker-thread activation or blocking waits on load completion: violates Engine ownership and risks visible stalls / stale mutation.
- Saving modified runtime state back into authored documents or unconditional disk writes on unload: corrupts design-time content and couples streaming to game-save policy.
