# Project, Scene, and Level Document Hardening Plan

> **For agentic workers:** Execute inline in this session, one task at a time. Every production behavior change is test-first. Do not commit or push.

**Goal:** Formalize Project, reusable Scene, and playable Level resources; add a versioned protobuf schema/codec while preserving readable JSON source and legacy project loading.

**Architecture:** `Project` remains the manifest and resource-I/O owner. `Scene` remains the shared entity graph; a thin `Level` document type reuses that graph and adds only level identity/metadata. `SceneInstance` references Scene resources only. A single document codec translates JSON/protobuf encodings into the same Scene/Level model. The existing Python script entry point remains distinct from the new generic resource entrypoint.

**Tech Stack:** Python 3.12, existing `ResourceId`, official `protobuf` runtime, `protoc` generation tool, pytest, existing editor/MCP/export paths.

---

## Ownership and compatibility decisions

| Responsibility | Canonical owner | Decision |
|---|---|---|
| Project manifest, project paths, document load/save orchestration | `core/project.py` | Extend; keep `project.json` ordinary JSON. |
| Reusable composition graph | `core/scene/scene.py` | Keep as the sole entity/hierarchy/runtime graph. |
| Playable document identity/metadata | new `core/scene/level.py` | Add a thin `Level(Scene)` document subtype; do not add a second ECS/world. |
| Entity/component records | `core/entity.py`, `core/component.py`, component-specific `to_dict`/`from_dict` | Reuse; add opaque preservation for unregistered component records. |
| Scene instance source | `core/scene/scene_instance.py` + `Project` resolver | Canonical `project://` Scene ResourceId; accept legacy project-relative `source_path`. Reject Level sources. |
| Scene/Level encoding | new `core/scene/document_codec.py` + `schemas/*.proto` | One protobuf-backed logical schema; JSON is canonical authoring source, PB is derived. |
| Resource classification | new `core/document_kind.py`, consumed by `editor/assets.py` | Classify explicit Scene/Level document kinds and known asset types; retain legacy JSON as Scene unless explicitly migrated. |
| Editor document routing | `editor/project_workflow.py`, `ui/editor_window.py`, `editor/builtin_features.py` | Reuse existing editor/Scene graph; route typed Level documents through the current Level Editor. |
| Standalone Run Project | `runtime/project_runner.py`, `editor/project_workflow.py` | Play remains embedded/current-document; Run Project launches the project script entry point in a tracked child process. |
| MCP/export | existing `tools/expra_mcp`, `export/` | Extend existing inspectors/actions and package closure; no new tool family. |

**Manifest compatibility:** canonical `entrypoint` is a project-relative resource reference. Legacy `start_scene` migrates to it. Legacy `entry_point` remains the Python launcher and migrates to `script_entry_point`; the Python launcher is not repurposed as a Scene/Level reference. A conflicting canonical+legacy field pair fails clearly.

**Document compatibility:** legacy flat `*.json` Scene files remain loadable as legacy Scenes. New sources use `*.scene.json` and `*.level.json`; examples are explicitly classified by their actual role. Newer unsupported schema versions fail before editor save can destroy data. Unknown component types remain opaque and round-trip intact.

## Implementation checkpoints

### 1. Prove startup/resource and recent-project invariants

Files: `tests/test_editor_texture_rendering.py`, `tests/test_editor_window_autosave.py`, `tests/conftest.py`, `ui/editor_pixel_renderer.py`, `ui/editor_window.py`, `editor/preferences.py`, `editor/project_workflow.py`.

- Add a RED regression: an empty/primitive-only editor frame renders without a project resource provider and emits no error; a Sprite frame without a provider still reports the texture failure.
- Add a RED regression: missing temporary recent-project paths are pruned; an existing but malformed project remains listed and reports its load failure.
- Isolate test preferences from `~/.expra/preferences.json`; provide a preferences-path seam for the MCP worker and editor tests.
- Run the two new tests before changing production code; then make the smallest fixes and rerun the owning test modules.

### 2. Define typed Scene/Level documents and resource identifiers

Files: new `core/document_kind.py`, new `core/scene/level.py`, `core/scene/scene.py`, `core/scene/__init__.py`, `core/entity.py`, `core/component.py`, `core/scene/scene_instance.py`, `tests/test_scene.py`, `tests/test_scene_instance.py`, new `tests/test_level.py`.

- RED: Scene and Level have distinct kind/ID/metadata; Level uses the normal entity graph; clone/instance boundaries reject Level-as-Scene; opaque unknown components survive load/save.
- GREEN: add the typed Level wrapper/subtype and round-trip-safe unknown component container in the canonical owners.
- Preserve entity IDs/order, hierarchy behavior, camera, registered custom components, and Scene Instance source identity.

### 3. Add schema definitions, generated bindings, and canonical codecs

Files: new `schemas/common.proto`, `schemas/scene.proto`, `schemas/level.proto`; new `tools/generate_protobuf.py`; generated bindings under `src/expra_engine/schema/generated/`; new `core/scene/document_codec.py`; `pyproject.toml`; `tests/test_document_codec.py`.

- RED: schema round-trips preserve IDs, parent order, cameras, component `type_id` plus recursive JSON values (including integer/float distinction), Level metadata, unknown component payload, and deterministic PB bytes.
- Define one shared Entity/Component/SceneGraph contract, permanent field numbers, package namespace `expra.schema.v1`, schema versions, and reserved-field rules.
- Use protobuf JSON mapping with stable snake_case and deterministic key order for new JSON sources; binary PB is derived from the same message model.
- Generation requires `protoc`; normal runtime never invokes it. Add an exact reproducibility test/command.

### 4. Migrate Project manifest and document I/O compatibly

Files: `core/project.py`, `runtime/project_runner.py`, `tests/test_project.py`, `tests/test_project_workflow.py`, `docs/PROJECTS.md`.

- RED: old schema-0/1 manifests with `start_scene`/`entry_point` load without rewriting; canonical manifests round-trip `entrypoint`, `script_entry_point`, `scenes`, and `levels`; bad/future versions fail before data mutation.
- Add one `load_document`/`save_document` dispatch owner; retain `load_scene` for Scene-only instance sources; keep a generic runnable document entrypoint.
- Keep project manifest data small; never embed entity graphs in `project.json`.

### 5. Route editor, AssetBrowser, Play, Run Project, and MCP by document kind

Files: `editor/assets.py`, `ui/asset_browser.py`, `editor/commands.py`, `editor/project_workflow.py`, `editor/builtin_features.py`, `ui/editor_window.py`, `runtime/project_runner.py`, MCP `_editor_worker.py`, `_static_runner.py`, `server.py`; focused editor/MCP tests.

- RED: Scene assets create Scene Instances; Level assets are not placeable as Scene Instances; opening a Level uses the existing editor graph; Save/Save As/Duplicate preserve document kind; Play uses the current document; Run Project launches the configured script entry point independent of the open document and is cleaned up on editor shutdown.
- Type labels are Project, Scene, Level, Script, Image/Texture, Audio, Folder, or File from canonical document/resource classification.
- MCP inspection reports entrypoint, current document kind/path, and scene/level registries; existing action names remain compatible where practical.

### 6. Migrate real projects and preserve external edits

Files: all `examples/{space_pong,blacksite_relay,neon_arena}/project.json`, relevant Scene/Level JSON files, example entry scripts, matching tests and docs.

- Migrate Blacksite main/Level 2/Level 3 as Levels; `security_door` as Scene; classify the composition demo from its actual purpose.
- Migrate Space Pong and Neon Arena by gameplay semantics, not filename alone.
- Preserve the existing user edit `examples/space_pong/scene/main.json` (`TransformComponent.scale_x == 3.0`) through migration.
- Prove legacy documents load and new source documents save deterministically.

### 7. Benchmark, export, and dogfood

Files: exporter runtime manifest/package closure, benchmark tests/tool, document/Scene/Level tests, MCP and example dogfood tests.

- Benchmark JSON vs PB decode, model construction, Scene Instance resolution, full load, bytes, and compile time for Space Pong and Blacksite Levels 1–3 plus 1000-entity synthetic data.
- Keep editor on JSON if PB does not materially improve complete load; compile PB for export only if data proves useful.
- Verify export contains required protobuf runtime/generated modules only when PB is used; run both exported Blacksite and Space Pong.
- Verify 1000-entity and many-instance bounds, 100 save/load cycles, 50 Play/Stop cycles, 20 Run Project process launches, cache invalidation, and no orphan process.

### 8. Final validation and report

- Run focused tests, full pytest, full Xvfb, Ruff, format check, pyright, mypy, compileall, diff-check, and protobuf reproducibility.
- Inspect full status/diff; preserve the user’s Space Pong edit; do not commit or push.
- Report all 60 requested items, exact test/check results, all changed files, and residual risks.
