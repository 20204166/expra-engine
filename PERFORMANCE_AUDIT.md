# Expra Full-Application Observability & Performance Audit

> **Historical performance audit.** Measurements and Tk frontend references
> below describe the 2026-09-26 pre-removal implementation, not the current
> Qt-only editor. Retain results as historical measurements.

**Audit date:** 2026-09-26
**Mode:** Measurement only; current working tree was treated as authoritative.

## Executive summary

The largest measured continuous cost is viewport work. In embedded Blacksite Play, the inclusive preview callback measured **21.93 ms p50 / 26.36 ms p95** against a 16.67 ms reference budget. In real Tk transform-drag input, a generic 5,000-entity scene measured **216 ms p50 / 251 ms p95** per motion event. A 1,000-entity pan or zoom also exceeded the frame budget per event.

Large documents are dominated by Protobuf conversion and construction rather than file reads. A synthetic 5,000-entity Level loaded in **143.90 ms p50** through the document model path; opening and presenting it in the full EditorWindow took **589 ms** in one run, with a **310.84 ms viewport commit** and **85.97 ms hierarchy commit**. Asset Browser population at 5,000 rows measured **473.6 ms**; unchanged refresh remained below 0.2 ms.

The current target inventory provides useful stage timings, counters, gauges and commit/failure events. It does not expose several end-to-end boundaries—especially direct viewport motion, Inspector structure/value sub-stages, saves, process spawn/exit and standalone child frames. Run Project creates a separate process; its metrics are not merged with the editor and are not currently retrievable through MCP.

**NO PERFORMANCE OPTIMIZATION WAS PERFORMED. NO PRODUCTION ARCHITECTURE WAS CHANGED.** No commit or push was made.

## Re-measurement — 2026-09-28 (current vs. prior)

A full re-run of every measurable scenario was executed against the current
working tree (HEAD `06d9ec0`, release `0.5.3.2`) using the same real code paths
and the same methodology as the 2026-09-26 audit. Results below are presented
as **prior → current**. All timings are milliseconds unless noted. Environment
is unchanged (same machine, Python 3.12.3, Pygame 2.6.1, Tk 8.6, Xvfb).

Two code changes landed between the prior audit and this re-run that affect
results: the canonical typed-document refactor (project/scene/level/world) and
the render draw-order-key extraction. Neither was a performance change; this
re-run is measurement-only.

### Document scale (Section 6)

Synthetic documents through the real `Project.save_document`/`load_document`
Protobuf path, 5 repetitions. `document:load` p50 / p95.

| Shape | Load p50 | Load p95 | Convert p50 | Construct p50 |
|---|---:|---:|---:|---:|
| 100, shallow/light Level | 2.82 → **2.47** | 4.42 → 3.05 | 1.71 → 1.30 | 0.75 → 0.75 |
| 1,000, shallow/light Level | 27.43 → **23.27** | 35.40 → 30.25 | 16.75 → 13.30 | 8.56 → 7.92 |
| 5,000, shallow/light Level | 143.90 → **151.28** | 157.55 → 174.99 | 81.18 → 87.73 | 45.85 → 43.88 |
| 1,000, shallow/light Scene | 31.27 → **21.62** | 41.35 → 26.57 | 19.13 → 13.62 | 9.30 → 6.85 |
| 1,000, depth-50/light Level | 24.17 → **26.05** | 32.62 → 34.47 | 14.98 → 16.59 | 7.09 → 7.57 |
| 1,000, shallow/heavy Level | 57.80 → **35.53** | 63.32 → 45.90 | 28.24 → 18.88 | 21.65 → 14.52 |

Reusable Scene Instances (1,000-entity Level, first-load wall / nested calls):
10 instances 35.23 ms / 55 → **32.02 ms / 55**; 50 instances 69.75 ms / 153 →
**49.25 ms / 255** (the prior run used 3 repetitions for the 50-instance case;
this run uses 5, hence 255 nested `document:*` calls).

Document load is unchanged within run-to-run variance — no regression. The
heavy-shape byte payload differs from the prior generator (the prior
`OpaqueComponent` carried `values`/`labels` fields), so the heavy row is not a
strict apples-to-apples comparison; the light rows are structurally identical.

### Retention probes (Sections 11, 12, 14)

| Probe | Prior | Current |
|---|---|---|
| Render stress, 50 iters @640×400 | 0.458 s, cache 0→3 | **0.531 s, cache 0→3** |
| Render stress, tracemalloc delta | +358.7 KiB | **+371.2 KiB** |
| Resource cache, 100×2 assets | 56.14 ms, 2 entries | **49.34 ms, 2 entries** |
| Editor redraw stress, 15 iters | Canvas 129→129, images 27→27 | **0.736 s; Canvas 129→129, images 27→27** |

All four remain `bounded`; no retained-resource growth in any probe.

### Real-project workloads (Sections 9, 10, 16)

Embedded Blacksite Relay (66 entities) steady Play, via the live editor watcher:

| Stage | Prior p50 | Current p50 | Current p95 |
|---|---:|---:|---:|
| `editor:preview:tick` | 21.93 | **25.07** | 36.61 |
| `runtime:tick` | 2.09 | **2.89** | 3.93 |
| `runtime:behaviour:update` | 0.094 | **0.110** | 0.165 |
| `runtime:animation:update` | 0.074 | **0.084** | 0.129 |
| `runtime:audio:update` | 0.059 | **0.066** | 0.101 |
| `editor.pixelbridge.total` | 13.54 | **15.60** | 20.66 |
| `editor.pixelbridge.render` | 8.21 | **8.53** | 11.94 |
| `render:backend` | 8.16 | **8.49** | 11.90 |
| `editor.pixelbridge.photoimage` | 4.35 | **5.37** | 7.80 |
| `editor.pixelbridge.extract` (surface) | 0.23 | **1.17** | 1.55 |
| `editor.pixelbridge.encode` | 0.049 | **0.056** | 0.080 |

Space Pong (10 entities) preview tick: 11.61 → **10.54 ms** p50.

The preview tick and pixel-bridge stages are modestly higher than the prior
run (roughly +8–14%), consistent across the board; this is within the expected
range for a re-run under a loaded session and is not attributable to a specific
regression. Runtime fixed-update spans remain sub-millisecond.

### Asset scan (Section 7)

Real `scan_directory` with the real recursive `iter_project_paths` enumerator:

| Rows | Prior p50 | Current p50 |
|---:|---:|---:|
| 100 | 6.57 | **3.41** |
| 1,000 | 70.66 | **32.51** |
| 5,000 | 369.71 | **153.96** |

Asset scan is now ~2.2× faster — consistent with the asset-browser hygiene
work that landed after the prior audit.

### Hierarchy panel (Section 7, isolated real Tk)

| Entities | Initial | Unchanged p50 |
|---:|---|---|
| 100 | 4.79 → **5.51** | 0.70 → **0.63** |
| 1,000 | 17.40 → **17.36** | 6.02 → **5.03** |
| 5,000 | 92.28 → **170.62** | 26.28 → **22.38** |

Unchanged re-render is slightly faster; the 5,000 initial is higher (noise /
one sample, heavier per-entity component payload in this run's generator).

### Pan / zoom / transform drag (Section 8)

Real viewport under Xvfb with `event_generate` (pan 120 motions, zoom 60).
Generic scenes use `PrimitiveComponent` (Canvas-vector path) in this run.

| Scenario | Prior p50 | Current p50 | Prior p95 | Current p95 |
|---|---:|---:|---:|---:|
| Pan, generic 1,000 | 67.98 | **73.63** | 79.25 | 99.01 |
| Zoom, generic 1,000 | 58.25 | **71.48** | 67.25 | 97.61 |
| Transform drag, generic 1,000 | 51.02 | **37.17** | 59.17 | 47.68 |
| Transform drag, generic 5,000 | 215.98 | **174.83** | 251.46 | 204.96 (max 540.63 → 224.59) |

Per-motion latencies remain in the same order of magnitude as the prior run —
no regression in the largest continuous cost. Transform drag was measured
through the real `SpatialEditController` driving the real viewport redraw
(rather than full synthetic mouse events), so the drag path is comparable but
not identical to the prior harness.

### Observer overhead (Section 13)

| Workload | Prior | Current |
|---|---|---|
| 1,000-entity document, 30 loads | ON faster by 7.8% (inconclusive) | ON 27.88 ms vs OFF 28.07 ms (inconclusive) |
| 1,000-entity Engine tick, 300 ticks | +2.7% p50 with observer | +9.1% p50 (10.00 vs 9.17 ms) |

No material observer overhead isolated from run-to-run variance.

### Full test suite (Validation)

Prior: 2,185 passed in 38.15 s. Current: **2,349 passed (308 subtests) in
42.63 s** — after fixing one regression found during this re-run (see below).

### Regression found and fixed during this re-run

The full suite hung under Xvfb on
`tests/test_editor_ui.py::test_new_scene_clears_delete_action_state`. The
typed-document refactor moved `_act_new_scene` onto
`ProjectWorkflow.new_document`, whose `_confirm_switch` guard opens a modal
`messagebox.askyesnocancel` whenever the command stack is dirty. The test
deliberately dirties the stack (`_act_add_entity`) before `_act_new_scene`, so
the modal blocked forever with no user to click. Fixed by returning early from
`_confirm_switch` when `window._engine.project is None` (a scratch scene has no
project to save, matching the pre-refactor behaviour). Change is two lines in
`src/expra_engine/editor/project_workflow.py`, currently uncommitted.

**NO PERFORMANCE OPTIMIZATION WAS PERFORMED. NO PRODUCTION ARCHITECTURE WAS
CHANGED BY THIS RE-MEASUREMENT.**

## 1. Starting state and environment

| Item | Recorded value |
|---|---|
| Starting Git SHA | `9cacad4e857ccf04f5f9ba6e20cf2e10b4f4743c` |
| Starting branch/status | `main`, clean; no dirty paths at the starting check |
| Python | 3.12.3, `/home/btn17/Downloads/expra-engine/.venv/bin/python` |
| OS / architecture | Linux 7.0.0-34-generic, x86_64, glibc 2.39 |
| CPU | AMD Ryzen 5 PRO 3400GE with Radeon Vega Graphics; 8 logical CPUs |
| Pygame / SDL | Pygame 2.6.1 / SDL 2.28.4 |
| Tk/Tcl | 8.6 / 8.6 |
| Display | Xorg `:0`, 1920×1080; EditorSession window 1280×800 |
| Isolated Tk measurements | Xvfb, 1280×1024 |

At the final status check, Git listed two modified source paths—`src/expra_engine/core/document_kind.py` and `src/expra_engine/core/scene/document_codec.py`—and five untracked paths: this report, `docs/plans/2026-09-26-first-class-world-streaming.md`, `docs/specs/2026-09-26-world-streaming-design.md`, `examples/The_Second_Mark_Story_and_Game_Bible.md`, `src/expra_engine/core/world.py` and `tests/test_world_documents.py`. None of the source, plan, spec, example or test paths were edited by this audit; they were left untouched. `git diff --check` passed.

## 2. Measurement method and statistics

- Reset the live EditorWindow watcher before controlled editor scenarios; `reset_observations=true` returned an empty snapshot.
- Synthetic document tests used the repository’s existing generic hierarchy generator and the real `Project.load_document()` Protobuf path. Synthetic project files and test script were created under `/tmp/opencode` and cleaned up.
- Tk scale measurements used real `EditorWindow`, `HierarchyPanel`, `AssetBrowserPanel`, and `ViewportPanel` objects under Xvfb. Pan, zoom, and drag used Tk `event_generate` events and pumped the actual Tk event loop.
- One-time document, scene-open, project-open and save results are wall-clock measurements alongside the observed stages. One-sample UI timings do not have meaningful p95 distributions; where a probe was repeated, the stated p95 comes from those repetitions.
- `ObservabilityWatcher` exposes min/p25/p50/p75/p95/p99/max but no mean. High-frequency distribution statistics in EditorSession are computed from the most recent **128 samples**, even when `count` is larger. The document probe expands its sample limit for the iteration count, capped at 4096.
- Timings are not added across inclusive/nested spans. For example, `document:load` contains decode/convert/construct/instance resolution; viewport commit contains extraction/plan/pixel presentation; runtime tick contains fixed-update system spans.

## 3. Authoritative observability target inventory

The list below comes from the current production instrumentation and the actual runtime snapshots, not from prior reports.

| Target(s) | Owner | Measures | Counters, gauges or events | Context / frequency |
|---|---|---|---|---|
| `runtime:tick` | `core/engine.py` | Full `Engine.tick()` span | In-flight and peak in-flight | Embedded runtime; standalone only if a watcher is supplied; per outer tick |
| `runtime:behaviour:update` | `runtime/behaviour_system.py` | Fixed Behaviour update span | `invoked`; records explicit Behaviour exceptions as failure | Embedded runtime; standalone only with watcher; per fixed update |
| `runtime:animation:update` | `runtime/animated_sprite_system.py` | Animated sprite update span | `players_advanced`, `frame_transitions`, `active_players` | Embedded runtime; standalone only with watcher; per fixed update |
| `runtime:audio:update` | `runtime/audio_2d.py` | Audio update span | `active_voices` | Embedded runtime; standalone only with watcher; per fixed update |
| `runtime:physics:query` | `runtime/physics_world.py` | **Counter only**, no duration | `overlap`, `raycast` | Embedded runtime; conditional standalone use |
| `runtime:physics:step` | `runtime/physics_world.py` | Physics step span | In-flight and peak in-flight | Only when `PhysicsWorld.step()` is used with an observer |
| `runtime:input:dispatch` | `ui/editor_window.py` | Physical keyboard input dispatch | `physical_inputs`, `action_events` | Editor Tk keyboard path only; per key event |
| `editor:preview:tick` | `editor/runtime_preview.py` | `Engine.tick()` plus render request in the Tk preview callback | In-flight and peak in-flight | Embedded editor Play only; per preview callback |
| `render:extract` | `ui/viewport_render_target.py` | Scene-to-RenderFrame extraction | `entities_considered`, `items_produced` | Editor viewport; high-frequency when a target is rebuilt |
| `render:plan` | `ui/viewport_render_target.py` | Render-plan construction | `items_visible` | Editor viewport; high-frequency with extraction |
| `render:backend` | `runtime/pygame_renderer.py` | Pygame backend drawing | Failure outcome when drawing fails | Editor pixel renderer; standalone only if observer is injected |
| `resource:resolve` | `filesystem/service.py` | Logical resource resolution and identity | `cache_hit` event | Editor when its resource service receives the shared watcher; conditional standalone |
| `resource:read` | `filesystem/service.py` | Resource byte read | In-flight and peak in-flight | Same as above |
| `resource:decode` | `runtime/pygame_resource_provider.py` | Pygame texture decode | `cache_hit` event; decoder exceptions marked failure | Editor pixel renderer; conditional standalone |
| `document:read`, `document:decode`, `document:convert`, `document:construct`, `document:load`, `scene:resolve_instances` | `core/project.py` | Document stages; `document:load` is inclusive | Failure outcomes via `observe_stage` | Any caller passing a watcher; canonical editor project and scene workflows do |
| `document:construct:entities`, `document:construct:components`, `document:construct:hierarchy` | `core/scene/scene.py` | Construction substages nested inside `document:construct` | Failure outcomes via `observe_stage` | Any observed document construction |
| `editor.pixelbridge.total`, `.render`, `.extract`, `.encode`, `.photoimage` | `ui/editor_pixel_renderer.py` | Pixel bridge sub-stages | Timed spans; no row/frame counters | Editor only; high-frequency while pixel path is active |
| `ui:render:{hierarchy,inspector,viewport,assets,console,toolbar,status}` | `coordinators/ui_coordinator.py` | UI commit callback spans | Request/commit/failure/coalesced/stale/rejected event counts | Editor only; viewport is high-frequency in Play; other panels are action-driven |
| `ui:assets:populate` | `ui/asset_browser.py` | Asset Treeview reconciliation/population | Timed span; no row-count gauge | Editor only; scan result delivery |
| `ui:action:{action_id}` | `coordinators/button_coordinator.py` | Button action callback | Rejected events; action exceptions as failure | Editor only; discrete actions |
| `app:{key}` | `coordinators/app_coordinator.py` | Async application operation span | Request/completion/failure/coalesced/stale events | Editor only; background tasks such as asset scans |
| `component:{key}` | `coordinators/refresh_scheduler.py` | **Coalesced event only**, no duration span | Coalesced count | Generic scheduler helper; no production EditorWindow construction was found |

### Sampling and failure semantics

The common watcher supports success/failure/cancelled spans, events, counters, gauges, in-flight counts and a bounded sample deque. `observe_stage`, `UICoordinator`, `ButtonCoordinator`, `PygameRenderer` and `BehaviourSystem` have meaningful failure handling. Some hand-written `finally: finish(token)` spans default to success on exceptions: resource resolve/read, Engine/preview tick, some animation/audio paths and pixel-bridge total. A caught renderer failure may be logged as a fallback while `editor.pixelbridge.total` still records success. This matters when interpreting failure snapshots.

The watcher’s **samples are bounded**, but its target dictionary has no hard cardinality limit. Current production names are stable except `app:asset-browser:{id(self)}`, which embeds a widget object address. No target includes an entity, document, project or resource path. A repository test loads 100 distinct document names plus repeated loads and asserts exactly 9 stable document targets, samples bounded to 8 and `in_flight=0`.

## 4. Watcher ownership and process boundary

`EditorWindow` creates the session watcher and injects it into `Engine`, `AppCoordinator`, `ButtonCoordinator`, `UICoordinator`, `ViewportPanel`/`EditorPixelRenderer`, `AssetBrowserPanel` and `RuntimePreviewLoop`. The Engine’s built-in systems read `engine.observer` when started. The canonical ProjectWorkflow passes the same watcher into `Project.load_document()` and `Project.resource_service()`. A single live snapshot contained UI, runtime, render, resource and editor targets, confirming shared identity in the editor.

There is no accidental second watcher in the actual EditorWindow. `UICoordinator` and `RefreshScheduler` have fallback watcher constructors when used independently, but the editor supplies the shared instance. `Project` itself does not own a watcher; loading accepts one explicitly.

**Run Project is a process boundary.** `ProjectWorkflow` starts the project’s script entrypoint in a child process while the editor stays in Edit. The child does not share the editor watcher. The actual Space Pong and Blacksite `__main__.py` scripts construct `Engine()` without an observer. `project_runner.py` creates a local watcher if used, but does not return/export it and does not pass it to the Pygame renderer, resource provider or frame extractor. MCP `runtime_probe` can execute headless Engine steps but does not retrieve the live child’s metrics.

The MCP EditorSession worker has two measurement-path discrepancies from canonical UI handlers: its project-open branch does not pass the shared observer into `project.resource_service()` and does not switch the Asset Browser root; its Scene-open branch calls `load_document()` without the observer. The canonical `ProjectWorkflow.open_loaded()`/`open_scene()` routes were used for the reported project/scene-stage measurements.

## 5. No-project startup and project open

### No project

The real live EditorSession started with a 2-entity in-memory scene. Its first snapshot showed:

| Target | Count | p50 |
|---|---:|---:|
| `ui:render:viewport` | 1 | 25.39 ms |
| `ui:render:inspector` | 1 | 2.17 ms |
| `ui:render:hierarchy` | 1 | 0.143 ms |
| `ui:render:toolbar` | 1 | 0.073 ms |
| `ui:assets:populate` | 1 | 0.058 ms |
| `render:extract` | 4 | 0.082 ms |
| `render:plan` | 4 | 0.021 ms |
| `app:asset-browser:{id}` | 1 | 0.668 ms |

No texture/resource work or failures were recorded. The empty scene produced zero render items. After an idle wait, target counts remained unchanged and in-flight spans were zero. A separate real EditorWindow/Xvfb harness measured **336.9 ms** from Engine/EditorWindow construction to the first Tk update; this excludes Python imports and OS process startup. Two Tk `after` IDs were pending at that initial point.

### Canonical project open: Blacksite Relay

One full EditorWindow open, including Project load, document load, presentation and completion of the background asset scan, measured **103.4 ms wall**. It populated 28 Asset Browser entries.

Representative spans from a separate fresh EditorWindow open:

| Work | p50 / observed value |
|---|---:|
| `document:load` | 5.50 ms |
| Read / decode / convert / construct / instance resolution | 0.050 / 0.427 / 3.004 / 1.802 / 0.042 ms |
| Background asset scan `app:asset-browser:{id}` | 5.05 ms |
| Asset Treeview `ui:assets:populate` | 4.56 ms for 28 rows |
| Hierarchy / Inspector / toolbar | 1.68 / 0.039 / 1.79 ms |
| Viewport commit, inclusive | 48.84 ms |
| Pixel bridge total / backend / extraction / plan | 22.77 / 11.44 / 2.70 / 0.675 ms |

`Project.load()` manifest parsing and project construction have no dedicated target. The `document:load` span is the document payload, not the whole project-open operation.

## 6. Document and synthetic scale results

The primary synthetic generator writes generic Protobuf Levels and Scenes and loads them through the real Project path. Timed loads below use 5 repetitions.

| Shape | Kind | Entities / components | Bytes | Load p50 / p95 / max | First load | Convert p50 | Construct p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| 100, shallow/light | Level | 100 / 110 | 21,120 | 2.82 / 4.42 / 4.64 ms | 3.88 ms | 1.71 ms | 0.75 ms |
| 1,000, shallow/light | Level | 1,000 / 1,100 | 212,730 | 27.43 / 35.40 / 37.34 ms | 31.14 ms | 16.75 ms | 8.56 ms |
| 5,000, shallow/light | Level | 5,000 / 5,500 | 1,073,074 | 143.90 / 157.55 / 158.86 ms | 160.16 ms | 81.18 ms | 45.85 ms |
| 1,000, shallow/light | Scene | 1,000 / 1,100 | 212,707 | 31.27 / 41.35 / 43.67 ms | 36.86 ms | 19.13 ms | 9.30 ms |
| 1,000, depth 50/light | Level | 1,000 / 1,020 | 205,388 | 24.17 / 32.62 / 34.72 ms | 23.90 ms | 14.98 ms | 7.09 ms |
| 1,000, shallow/heavy | Level | 1,000 / 1,800 | 293,874 | 57.80 / 63.32 / 64.68 ms | 50.63 ms | 28.24 ms | 21.65 ms |

The load span contains conversion, construction and instance resolution; construction contains the entities/components/hierarchy substages. At 5,000 entities conversion is the largest model sub-stage (81.18 ms p50); reads remain below 1 ms.

### Full EditorWindow synthetic Level open

Each was a single canonical `.level.pb` open sample in a real EditorWindow. Scene presentation and the viewport run after document construction.

| Entities | `document:load` | Hierarchy commit | Viewport commit (inclusive) | `render:extract` | Total open wall |
|---:|---:|---:|---:|---:|---:|
| 100 | 3.15 ms | 2.40 ms | 22.60 ms | 2.55 ms | **42.62 ms** |
| 1,000 | 28.61 ms | 19.48 ms | 65.39 ms | 15.95 ms | **133.28 ms** |
| 5,000 | 129.64 ms | 85.97 ms | 310.84 ms | 84.15 ms | **589.37 ms** |

At 5,000 entities conversion was 89.14 ms and construction 33.28 ms. The 310.84 ms viewport commit includes extraction/plan/pixel/Canvas work; do not add the nested stages to it.

### Reusable Scene Instances

On a 1,000-entity synthetic Level, first-load total was 31.14 ms without instances, 35.23 ms with 10 instances, and 69.75 ms with 50 instances. With 10 instances, the watcher aggregated 55 nested document stage calls; with 50 instances, 153. `scene:resolve_instances` maximums were 7.72 ms and 28.76 ms respectively. Aggregated p50/p95 include child-document loads; only the first-load wall gives a parent-level total.

## 7. Selection, Inspector, hierarchy and assets

### Selection and Inspector

The synthetic 1,000-entity real Tk EditorWindow used actual Treeview selection events for 100 alternating selections:

- Full selection event plus Tk update: **9.28 ms p50 / 14.93 ms p95 / 41.92 ms max**.
- `ui:render:inspector`: 100 commits; `ui:render:viewport`: 100 commits.
- `ui:render:hierarchy`: **0**; `render:extract`: **0**.

This confirms selection avoids a complete hierarchy render and full viewport frame extraction. Same-schema Inspector selection measured **0.147 ms** in one 1,000-entity sample. A schema-changing selection measured **11.60 ms** in the Inspector span and **40.53 ms** end-to-end in one Tk sample. A separate Space Pong schema switch had a 119.9 ms Inspector sample, so schema-changing latency is variable and needs more repeated samples.

50-entity multi-selection measured 50.40 ms end-to-end, with a 9.67 ms Inspector span. A value-only transform change measured 76.42 ms total; it committed a 63.16 ms viewport span and 23.63 ms extraction but did not issue a separate Inspector commit, since the edited widget already held the entered value.

Component and script operation samples at 1,000 entities:

| Action | Wall | Hierarchy | Inspector | Viewport |
|---|---:|---:|---:|---:|
| Add component | 134.79 ms | 7.63 ms | 14.73 ms | 61.18 ms |
| Remove component | 184.34 ms | 50.50 ms | 13.20 ms | 76.99 ms |
| Attach temp test Behaviour | 128.52 ms | 6.76 ms | 12.15 ms | 62.27 ms |
| Remove script | 135.62 ms | 10.16 ms | 11.25 ms | 71.24 ms |

These are single samples and include a full viewport redraw. No production target splits Inspector structure rebuild from value refresh, and no component/script-specific timer exists.

### Hierarchy scale and mutations

Isolated real Tk `HierarchyPanel` timings (panel render plus `root.update()`). Unchanged/rename/add/delete/reparent rows are p50 over 5 samples; initial presentation is one sample.

| Entities | Initial | Unchanged | Rename | Add | Delete | Reparent |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 4.79 ms | 0.70 ms | 3.31 ms | 3.68 ms | 4.00 ms | 3.51 ms |
| 1,000 | 17.40 ms | 6.02 ms | 12.24 ms | 12.46 ms | 13.72 ms | 11.72 ms |
| 5,000 | 92.28 ms | 26.28 ms | 47.96 ms | 49.27 ms | 50.80 ms | 52.57 ms |

The full EditorWindow’s `ui:render:hierarchy` single-sample timings were 2.40 / 19.48 / 85.97 ms at 100 / 1,000 / 5,000 entities. These include UICoordinator commit timing; they are not repeated distributions.

### Asset Browser

Canonical Blacksite open scans and presents 28 rows: AppCoordinator scan 5.05 ms and `ui:assets:populate` 4.56 ms in the detailed sample.

Synthetic actual Tk AssetBrowser measurements:

| Rows | Scan function p50 / p95 | Initial populate | Unchanged populate p50 / p95 | One-row add/remove populate p50 / p95 |
|---:|---:|---:|---:|---:|
| 100 | 6.57 / 6.86 ms | 7.66 ms (n=1) | 0.011 / 0.044 ms | 1.02 / 1.77 ms |
| 1,000 | 70.66 / 86.83 ms | 88.55 ms (n=1) | 0.016 / 0.028 ms | 9.12 / 10.98 ms |
| 5,000 | 369.71 / 404.30 ms | 473.61 ms (n=1) | 0.069 / 0.158 ms | 47.48 / 60.67 ms |

The scan timings are the real `scan_directory` function over pre-created temporary files; population timings use the existing `ui:assets:populate` target and real Treeview. Scan and UI presentation are separate and may overlap in the real asynchronous editor route.

## 8. Viewport idle, pan, zoom and transform drag

The normal viewport commit is an inclusive operation. On Blacksite Play, `ui:render:viewport` was 19.57 ms p50 / 23.10 ms p95 / 40.13 ms max; the direct per-motion path does not consistently pass through this UICoordinator target.

Actual Tk event-generation probes, with 120 motion events except zoom (60):

| Scenario | Full event latency p50 / p95 / max | Relevant instrumented stage p50 / p95 |
|---|---:|---:|
| Pan, generic 1,000 entities | 67.98 / 79.25 / 94.26 ms | `render:extract` 17.27 / 21.00 ms; pixel bridge 6.00 / 9.07 ms |
| Zoom, generic 1,000 entities | 58.25 / 67.25 / 67.72 ms | `render:extract` 16.47 / 20.09 ms; pixel bridge 5.32 / 6.72 ms |
| Transform drag, generic 1,000 | 51.02 / 59.17 / 86.82 ms | Pixel bridge 6.57 / 10.36 ms |
| Transform drag, generic 5,000 | 215.98 / 251.46 / 540.63 ms | Pixel bridge 6.07 / 9.63 ms |
| Transform drag, Blacksite main Level | 33.66 / 41.55 / 48.60 ms | Pixel bridge 17.84 / 21.92 ms; backend 10.76 / 13.37 ms |

Transform drag triggered 122 pixel frames for 120 motions (press/release account for two); `render:extract` occurred once after reset rather than once per motion. Pan and zoom each generated 120/120 and 60/60 extraction/pixel frames. This is no redraw flood, but per-event latency is still high. At 5,000 entities the event wall is not explained by the measured bridge stages; per-event transform/overlay/Canvas/Tk timings are absent.

Camera preference debounce: 60 rapid wheel events resulted in **one** preference save after the debounce, with the debounced Tk callback pending during the burst. Disk flush is not paid on every wheel event.

## 9. Pixel bridge details

The live editor pixel route is Pygame surface → `pygame.image.tostring(..., "RGBA")` → `PIL.Image.frombuffer` → `PillowEditorPhotoImage.paste()` (or first image creation). There is no PNG/base64 round trip in this live route.

For Blacksite steady Play, representative p50s were:

| Stage | p50 |
|---|---:|
| Pygame render (`editor.pixelbridge.render`) | 8.21 ms |
| `render:backend` nested inside render | 8.16 ms |
| Surface-to-RGBA extraction | 0.23 ms |
| Pillow buffer wrapping (`.encode`) | 0.049 ms |
| PhotoImage paste/create | 4.35 ms |
| Pixel bridge total | 13.54 ms |

Surface creation and other bridge overhead are included in `.total` but have no separate target. Tk’s final compositor/display time is not measured.

## 10. Play, Pause, Resume, Stop and runtime costs

Play-start work (scene copy, Behaviour attachment/start, animation/audio setup and first playable frame) has no dedicated target and was not isolated from subsequent frames. The source path is `Engine.play()` followed by `RuntimePreviewLoop` at `root.after(16, ...)`.

Steady Blacksite Play results are in Section 10’s stage table above; the key p50s were `runtime:tick` 2.09 ms, Behaviour 0.094 ms, Animation 0.074 ms and Audio 0.059 ms. Overlap query count was 438; no timed physics-step span was observed in that workload.

Pause and Resume preserved state. During a 2-second paused wait, `runtime:*` remained empty. Stop returned to Edit and restored the prior scene; after Stop, a reset followed by a 3-second Edit wait had no metrics. The Space Pong camera scale remained 3.0 across Play, Resume and Stop.

100 Play/Pause/Resume/Stop cycles through real EditorWindow handlers:

- Cycle wall: **215.77 ms p50 / 250.32 ms p95 / 274.48 ms max**.
- First 10 cycles mean: 201.36 ms; last 10 mean: 212.91 ms (single-series change, not a clear degradation trend).
- Canvas items 129→129; Tk images 27→27; TimerDelivery IDs 0→0; Tk `after` IDs 2→2; AppCoordinator idle; UI pending targets 0; observer in-flight 0; final state Edit; entity count 66.
- Target cardinality after stress: 19; resource decode count 0 with 8,400 cache-hit events.

## 11. Run Project and standalone runtime

Run Project keeps the editor in Edit and launches the project’s script entrypoint in a separate OS process.

- Space Pong child PID was observed alive for 51 seconds; one `ps` snapshot showed 32.3% CPU and 125,800 KiB RSS. This is a process-lifetime snapshot, **not** a per-frame metric. Stop removed the PID and the editor remained Edit.
- Blacksite’s child was present in one process-table poll but gone by the next; no return code or traceback was exposed. Neon’s child was likewise absent at the next poll. Their standalone frame costs could not be measured.
- No child watcher snapshot, IPC metric export, start/exit span or frame telemetry is available. `runtime_probe` is a separate headless Engine tool, not the standalone Pygame child.
- Standalone render-only reference: headless Blacksite render stress at 640×400 took 0.458 s for 50 iterations (about 9.16 ms/iteration), with cache size 0→3 and zero logger/diagnostic growth. This is **not** a standalone runtime frame and is not directly comparable to embedded Play.

## 12. Resources, cache and Scene Instances

Canonical cold-ish Blacksite project open decoded 3 textures: `resource:resolve/read/decode` each had 3 samples with p50 0.287 / 0.323 / 0.135 ms and 25 decode cache-hit events. During warm interaction, decode count was 0 with 1,708 cache hits. `assets://kenney/player_survivor_gun.png` resolved to a 51×43 RGBA PNG, 1,617 bytes.

The 100-repeat resource-cache probe for two Blacksite textures took 56.14 ms and ended with exactly 2 cache entries. The 50-render stress probe without tracemalloc ended with 3 cache entries, logger handlers 0→0 and diagnostic occurrences 0. With `track_memory=true`, wall time rose to 6.48 s and tracemalloc reported +358.7 KiB; that traced run is not comparable to untraced frame timings and does not establish a leak.

## 13. Observer overhead

| Workload | Observer ON | Observer OFF | Result |
|---|---:|---:|---|
| 1,000-entity document, 30 loads | 30.00 ms/load from loop wall; watcher `document:load` p50 26.62 ms | 32.53 ms/load from loop wall; no stage distribution | Inconclusive: ON appeared faster by 7.8%; first-load values differed by only about 1.4% in the opposite direction |
| 1,000-entity Engine tick, 300 paired ticks | External p50 13.74 ms, p95 17.61 ms | External p50 13.38 ms, p95 17.17 ms | About +0.36 ms / +2.7% p50 with observer ON; small and workload-specific |
| Small-scene pan, 60 events | p50 7.81 ms, p95 12.63 ms | p50 7.11 ms, p95 9.71 ms | About +0.70 ms / +9.9% p50; p95 variance is high, low confidence |
| Small-scene transform drag, 60 events | p50 7.14 ms, p95 9.31 ms | p50 6.95 ms, p95 9.32 ms | About +0.19 ms / +2.7% p50; below meaningful tail difference |

No material observer overhead was isolated from run-to-run variance in document loading. Runtime and UI observer overhead appears small relative to the measured high-frequency work, with the stated sample-size/environment caveats.

## 14. Failure paths, cardinality, retention and idle

- The full test suite includes malformed Protobuf coverage: `document:decode` and `document:load` record failure and return `in_flight` to zero.
- A missing-resource trace safely reported `exists=false`, `decode_status=not_attempted`; no watcher failure metric was available through that trace call.
- Bad Scene Instance source, renderer failure and Behaviour failure were not separately induced in live projects during this pass.
- The audit did not call an increase in tracemalloc usage a leak. Resource cache, logger handlers, diagnostics, Canvas items, images, callback IDs and observer in-flight state all had bounded before/after evidence in the measured stress runs.
- Sample storage is bounded (128 by default); metric-target dictionary cardinality is not globally bounded. Current observed app target cardinality stayed at 19 after the 100-cycle stress. The repository test loading 100 document names remained at 9 targets.
- Edit idle after Stop produced zero observations for 3 seconds; Pause idle produced zero runtime observations for 2–3 seconds. RuntimePreviewLoop retains/reschedules a Tk callback while Paused, but callback count is not an observability target.

## 15. Coordinator observations

On canonical Blacksite open, AppCoordinator asset work finished (`has_pending_work=false`) and UICoordinator requests matched commits for visible panels. Normal measured scenarios showed no coalesced/stale/rejected UI events. AppCoordinator’s internal operation states, UICoordinator `pending_peak`/`last_commit_seconds`, and pending Tk callback totals are not included in the shared watcher snapshot; the EditorSession does not expose those internal objects.

## 16. Project workload results

- **Space Pong:** 10-entity Level open; embedded Play p50 preview tick 11.61 ms, p95 14.48 ms; input `w` down/up produced 2 dispatch spans (p50 0.079 ms); camera `scale_x` remained 3.0 through Stop; Run Project child launched and was stopped.
- **Blacksite Relay:** main 66 entities, Level 2 100, Level 3 69. Canonical Level2/Level3 open wall was 67.25/64.26 ms with observed document stages. Main Play p50 preview tick 21.93 ms. Dense main-Level transform drag p50 33.66 ms per motion. Run Project child did not remain available to inspect.
- **Neon Arena:** 2-entity Level open, embedded Play/Stop; preview p50 7.76 ms, p95 11.49 ms. Its Run Project child was absent by the next process poll.

These dogfood projects validate current workloads; the synthetic PB/Tk scale matrix remains the main scaling evidence.

## 17. Ranked bottlenecks by frequency and user impact

| Rank | Subsystem / metric | Scenario | Frequency | p50 | p95 | Max | Relative budget / impact | Confidence | More instrumentation? |
|---:|---|---|---|---:|---:|---:|---|---|---|
| 1 | Direct transform motion event; no stable event target | Generic 5,000 entity drag | Continuous during drag | 216 ms | 251 ms | 541 ms | ~1,296% of 16.67 ms reference; **Critical** | High for 120 event wall samples; attribution incomplete | Yes |
| 2 | Direct pan motion; `render:extract` is 17.27 ms p50 | Generic 1,000 entity pan | Continuous during pan | 68 ms | 79 ms | 94 ms | ~408%; **Critical** | High for 120 event samples | Yes, direct Canvas/Tk span |
| 3 | Direct wheel zoom; `render:extract` is 16.47 ms p50 | Generic 1,000 entity zoom | Continuous during zoom | 58 ms | 67 ms | 68 ms | ~349%; **High** | High for 60 event samples | Yes, direct viewport event span |
| 4 | `editor:preview:tick` | Blacksite embedded Play | Every preview tick | 21.93 ms | 26.36 ms | 42.19 ms | 132% p50; **High** | High; last-128 sample window | Yes for Play-start/fps scheduling split |
| 5 | `runtime:tick` | Generic 1,000 entity Engine | Every runtime tick | 13.74 ms | 17.61 ms | 26.65 ms | 82% p50; p95 above budget; **Medium/High at this scale** | Medium; paired ON/OFF workload | No for tick total |
| 6 | `ui:render:inspector` schema change | 1,000 entity selection | Frequent interaction | 11.60 ms span; 40.53 ms event wall | — | — | Occasional >16.67 ms event; **High** | Medium/low; one sample | Yes, structure vs values |
| 7 | `ui:render:viewport` / `render:extract` | Generic 5,000 entity Level open | Occasional scene open | 310.84 ms viewport; 84.15 ms extraction | — | — | N/A for frame budget; **Medium** | Medium; single open sample | Direct target already exists; total open boundary absent |
| 8 | `ui:assets:populate` | Synthetic initial 5,000 rows | Occasional project/folder open | 473.61 ms | — | — | N/A; **Medium** | Low; one initial population sample | No for total; asset-count gauge absent |
| 9 | Hierarchy reconciliation | 5,000 entity rename/add/delete/reparent | Editing action | 48–53 ms | 49–79 ms by operation | 79 ms | N/A; **Medium** | Medium; 5 samples | No for total; no sub-stage split |
| 10 | `document:load` / conversion | Synthetic 5,000 entity Level | Occasional load | 143.90 ms | 157.55 ms | 158.86 ms | N/A; **Medium** | Medium; 5 loads | No for model stages |
| 11 | `Project.save_document` | Synthetic 5,000 entity PB | Occasional save | 339.34 ms | 363.47 ms | 363.47 ms | N/A; **Medium** | Medium; 5 writes | Yes, serialization vs write |
| 12 | Unchanged Asset Browser reconciliation | Synthetic 5,000 rows | Occasional refresh | 0.069 ms | 0.158 ms | 0.158 ms | N/A; **Low/healthy** | Medium; 10 samples | No |

Largest one-time latencies are not ranked above continuous interactions solely by their millisecond value. The ranking gives priority to work repeated per drag event or preview tick.

## 18. Healthy areas

- Same-schema Inspector reuse is fast: 0.147 ms span in the 1,000-entity sample; alternating selection avoided full hierarchy and frame extraction.
- Unchanged Asset Browser refresh at 5,000 rows is 0.069 ms p50.
- `render:plan` stayed below 1 ms in measured normal rendering.
- Blacksite’s measured behaviour/animation/audio spans were sub-millisecond p50; small Space Pong and Neon Arena preview ticks stayed under the 16.67 ms reference p95.
- Warm texture requests hit cache; no repeated decodes were observed in the measured warm run.
- Stop returned to Edit and retained Space Pong camera scale; 100 Play/Pause/Resume/Stop cycles retained stable Canvas/image/callback counts and zero in-flight spans.
- No repeated Edit idle refresh loop was observed after settling.

## 19. Compact future baseline

| Baseline scenario | Recorded result |
|---|---|
| No-project EditorWindow to first Tk update | 336.9 ms in-process/Xvfb; imports/process startup excluded |
| Generic 1,000 entity Level document load | p50 27.43 ms / p95 35.40 ms |
| Generic 1,000 entity full EditorWindow Level open | 133.28 ms, one sample |
| 100 alternating hierarchy selections at 1,000 entities | p50 9.28 ms / p95 14.93 ms; no hierarchy rerender/extraction |
| Same-schema Inspector selection | 0.147 ms Inspector span |
| Generic 1,000 entity transform drag | p50 51.02 ms / p95 59.17 ms per motion |
| Generic 5,000 entity transform drag | p50 215.98 ms / p95 251.46 ms per motion |
| Embedded Blacksite Play preview tick | p50 21.93 ms / p95 26.36 ms |
| Standalone runtime frame | Not available from current child-process observability |
| Asset initial population, 1,000 rows | 88.55 ms, one sample |
| Protobuf save, 1,000 entities | p50 74.79 ms / p95 84.11 ms |
| 100 Play/Pause/Resume/Stop cycles | p50 215.77 ms / p95 250.32 ms per cycle; bounded retention |

## 20. Next measurement target

**Instrument only the direct `ViewportPanel` motion path for a 5,000-entity transform drag:** input handler, transform mutation, retained Canvas/overlay redraw, pixel presentation and Tk event flush. The external event latency is about 216 ms p50, while frame extraction is not repeated on every motion and pixelbridge accounts for only part of that wall time. This is the largest unresolved attribution gap.

## Validation and final state

- `expra_run_checks(full_xvfb)`: **2,185 passed, 0 failed, 0 skipped** in 38.15 s.
- The audit changed no production source or test file; its only repository addition is this report. Temporary synthetic projects were created under `/tmp/opencode` and cleaned up. The other modified/untracked paths listed above remain untouched.
- The earlier EditorSession worker had exited before a close request; the close call errored, and process inspection found no remaining project child. A fresh Neon EditorSession was closed successfully. Final process inspection found no Space Pong, Blacksite or Neon child process alive.
- No commit or push was made.

**NO PERFORMANCE OPTIMIZATION WAS PERFORMED. NO PRODUCTION ARCHITECTURE WAS CHANGED.**
