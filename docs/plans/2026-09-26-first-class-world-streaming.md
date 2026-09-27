# First-Class World Streaming Implementation Plan

> **For agentic workers:** Implement inline, task-by-task with TDD. Do not commit; preserve the untracked game bible.

**Goal:** Add a first-class World document that streams ordinary authored Levels through the existing Expra runtime and editor.

**Architecture:** A World is lightweight project metadata containing stable Level-instance descriptors and validated named-anchor connections. A runtime `WorldStreamingSystem` owns bounded background document loads, explicit residency, stale-result fencing, activation, session deltas, and diagnostics; active Level entities continue through Expra's existing Scene/Entity/Component systems. World-scale streaming is separate from future Level-internal terrain chunks.

**Tech Stack:** Python 3.12, deterministic protobuf, existing `Project`/document codec, `AppCoordinator` delivery/concurrency primitives where runtime-safe, `RuntimeSystem`, `UserDataStore`, Tk editor, Pygame runtime/export, pytest.

---

## File map

- `schemas/world.proto`, `schemas/level.proto`, `tools/generate_protobuf.py`, generated `schema/generated/*_pb2.py`: versioned World wire format and envelope.
- `core/world.py`, `core/document_kind.py`, `core/scene/level.py`, `core/scene/document_codec.py`, `core/project.py`: canonical documents, validation, safe project paths, non-publishing reads, persistence.
- `core/scene/world_anchor.py` and component registry/schema: named Level entrances/exits as ordinary entity components.
- `runtime/world_streaming.py`, `runtime/world_state.py`, `core/engine.py`, runtime behaviour/physics/audio/animation/render adapters: residency and lifecycle on the owner thread.
- `editor/project_workflow.py`, `ui/editor_window.py`, `ui/asset_browser.py`, new focused World editor panel/viewport overlay: World create/open/save/duplicate/inspect and connection authoring.
- `runtime/project_runner.py`, `export/*`, `tools/expra_mcp/*`: Run Project, dependency inclusion, and World inspection/debugging.
- Focused new tests in `tests/test_world*.py`, plus existing codec/project/engine/export/editor tests.
- `docs/specs/2026-09-26-world-streaming-design.md`: reviewed architecture and reference matrix.

## Tasks

### Task 1 — World domain and typed persistence

- [ ] Write failing tests for deterministic World/connection round-trip, duplicate IDs, invalid references, bad finite origins, and path traversal.
- [ ] Verify each regression fails against unchanged code for the missing World contract.
- [ ] Add World models, `DocumentKind.WORLD`, protobuf schema/envelope, codec dispatch, reproducible bindings, and Project world registration/save/load while preserving Scene/Level APIs.
- [ ] Run World tests, then `test_document_codec.py` and `test_project.py`.

### Task 2 — Anchors and pure graph decisions

- [ ] Add tests for unique named anchor resolution, directed/bidirectional connections, deterministic neighbor lookup, initial entry, and transition validation.
- [ ] Verify RED, then add the anchor component and pure graph/streaming-policy code in canonical owners.
- [ ] Run new tests and component/Level integration tests.

### Task 3 — Residency, bounded async load, activation

- [ ] Test state transitions, load budget, cancellation, stale completion after teleport/World switch, preload hysteresis, priority ties, and failed destination atomicity with a deterministic fake loader.
- [ ] Verify RED for each missing invariant before runtime edits.
- [ ] Implement the runtime owner with owner-thread completion publication; load only selected Level documents; activate/deactivate ordinary entities atomically; expose multiple active Levels and generic anchors.
- [ ] Run state-machine tests, owning runtime tests, then engine/behaviour/physics/audio/animation/render integrations.

### Task 4 — Session state, transitions, observability

- [ ] Test authored Level bytes remain unchanged across unload/reload, changed/deleted entity restoration, save/load through `UserDataStore`, and write failure retaining a recoverable resident Level.
- [ ] Implement in-memory Level deltas and versioned opt-in World-session serialization, transition modes, bounded metrics, and structured snapshots.
- [ ] Run persistence, transition, observer-failure, Play/Stop and traversal stress tests.

### Task 5 — Editor, Run Project, export, MCP

- [ ] Add failing editor workflow tests for World open/save/reopen and Level/connection selection without constructing all Levels.
- [ ] Add Run Project and export tests proving World entrypoint/reference closure; add MCP snapshot tests with the same production runtime owner.
- [ ] Implement only through the existing editor/runtime/export/MCP ownership paths; do not add a second renderer or loader.
- [ ] Run real Tk editor acceptance, headless Run Project, export verification, and MCP protocol tests.

### Task 6 — Example, performance, final validation

- [ ] Add a generic small World example with seamless and fade connections and no game-specific systems.
- [ ] Measure graph lookup/update at 10/100/1,000/10,000 descriptors where practical; verify bounded workers, queues, state maps, observations, and post-unload references.
- [ ] Run configured full, Xvfb, export, MCP, protobuf reproducibility, Ruff/format, Pyright, Mypy, compile, and diff checks; report every timeout/failure exactly.
- [ ] Audit final status and preserve all pre-existing user work; do not commit or push.
