# Space Pong Final Report

**Scope:** Task 8 after `ed0fc68`. This report audits Tasks 1-7 and records
release verification. No reference repository was modified.

## POLISH / MULTI-ENGINE EXTRACTION AUDIT

Space Pong uses generic Expra components and services. The project owns scene
data, labels, colors, tunables, input bindings, and `SpacePongBehaviour`; Expra
owns component registration, extraction, rendering contracts, runtime UI,
physics queries, lifecycle, editor commands, and export. No engine module
branches on Space Pong names.

### INSPECTOR

`PropertyDescriptor`, `ComponentTypeSpec`, `CommandStack`, and the inspector
metadata controls support typed fields, invalid-input rejection, required and
duplicate policies, stale-target no-ops, and undo/redo. The real-Tk evidence
selected `space-pong-controller`, changed `winning_score` 3 to 5 and a left
collider height 12 to 14, undid both, and saved the original scene.

### VISUAL COMPONENTS

`PrimitiveComponent`, `SpriteComponent`, and `TextComponent` serialize only
backend-neutral values. `extract_render_frame` composes transforms and orders
phase/layer/entity deterministically while skipping disabled, hidden, or
malformed visuals. The Space Pong scene contains generic primitives and text;
there is no Space-Pong extraction branch.

### PHYSICS / COLLISION EDITING

`ColliderComponent` validates rectangle/circle geometry and serializes scalar
data. `PhysicsWorld2D` provides deterministic overlap, nearest raycast,
layer/mask filtering, and trigger enter/stay/exit using the existing
`HitResult2D` and `TriggerEvent` contracts. Editor outlines are derived data,
not serialized preview state.

### RUNTIME HUD/UI

`GameCanvas`, `Panel`, `Label`, `Button`, layout resolution, focus, pointer
capture, and renderer-neutral draw commands are adapted by the Pygame runtime.
Space Pong builds its HUD from project-owned script data, covers score/win,
pause/resume, restart, hit feedback, and resize-stable reference-resolution
layout. The test path uses an injected backend because this environment has no
installed `pygame` module.

### NEON / VISUAL EFFECTS

The implementation uses generic colors, layered primitives, text, material
opacity/tint, outline/glow approximation, and existing timeline/tween
contracts. Particles and trails were not added; layered primitives are the
deliberate Space Pong fallback. Unsupported blend modes are reported rather
than silently emulated.

### EDITOR PREVIEW

`build_editor_render_target` and `ViewportPanel` consume the same
`RenderFrame` extraction data as runtime rendering. Tk-only grid, axes, labels,
selection, collider outlines, pan/zoom, frame-selected, and frame-scene remain
editor overlays. Real Tk tests under `xvfb-run` passed; no screenshot artifact
was generated.

### SOURCE MATURITY

The source checkouts were used for contract and test-intent comparison:
System Analyzer (`UNLICENSED`), Ursina (MIT), PPB (Artistic License 2.0), and
MiniPyEngine (MIT). Expra implementations were rewritten around existing Expra
ownership boundaries. Bundled reference assets were not copied.

### implementations substantially copied/adapted

None. No source implementation was copied. Ursina, PPB, and System Analyzer
symbols are recorded in `docs/POLISH_EXTRACTION_MAP.md` as behavior/test-intent
references only. MiniPyEngine was considered for narrow object/material
patterns but contributed no copied code or assets.

### tests ported/adapted

No test file was copied. Adapted intent is covered by new Expra tests for typed
editing and stale targets, deterministic render ordering and malformed data,
UI states/layout/focus/pointer capture, collider contacts/raycast/trigger
lifecycle, editor preview clipping/selection/camera behavior, and the complete
Space Pong workflow.

### provenance/license updates

The parity map now records source symbols, behavior retained, coupling removed,
Expra destinations, tests, evidence, and license status for Tasks 1-7. There is
no copied third-party implementation or asset requiring an additional notice;
the System Analyzer source is explicitly marked `UNLICENSED` and was not copied.

### REWRITTEN FROM SCRATCH DESPITE PROVEN SOURCE IMPLEMENTATION

`PhysicsWorld2D`, collider serialization, runtime UI models, render extraction,
editor preview adaptation, and Space Pong project code were written from
scratch despite proven source behavior or test intent. This preserves Expra's
`Engine`/`Scene`/`Entity`/`Component`, renderer, command, and Tk/Pygame adapter
boundaries instead of importing another engine's ownership model.

### SPACE-PONG-SPECIFIC ENGINE HACKS

**None.** Project-specific behavior is confined to
`examples/space_pong/`; generic engine code does not inspect project, entity,
label, or script names.

## Verification

### Focused suites

Command:

```text
PYTHONPATH=src python3.12 -m pytest -q tests/test_component_schema.py tests/test_editor_ui.py tests/test_editor_commands.py tests/test_render_extractor.py tests/test_runtime_rendering.py tests/test_pygame_renderer.py tests/test_runtime_ui.py tests/test_pygame_runtime.py tests/test_physics_world.py tests/test_runtime_physics.py tests/test_editor_render_targets.py tests/test_project_workflow.py tests/test_export.py tests/test_export_exporter.py tests/test_space_pong.py
```

Result: `204 passed in 70.11s`.

### xvfb real-Tk tests

Command:

```text
xvfb-run -a env PYTHONPATH=src python3.12 -m pytest -q tests/test_editor_ui.py tests/test_editor_render_targets.py tests/test_editor_window_autosave.py
```

Result: `34 passed in 4.31s`.

### Full suite and static checks

`PYTHONPATH=src python3.12 -m pytest -q` resulted in `1194 passed, 2
 warnings, 147 subtests passed in 71.75s`. Warnings were the existing editor
window soft line-count warning and an intentional duplicate zip member test.

`python3.12 -m compileall -q src tests examples` passed. `git diff --check`
passed. Ruff, Pyright, and Mypy were not run; they are not treated as passes.

### Editor, export, and runtime evidence

The xvfb editor workflow reported:

```json
{"entities": 9, "opened": "Space Pong", "paused": "paused", "reopened": ["Space Pong", 9], "resumed": "play", "saved": true, "stopped": "edit"}
```

The real export command was:

```text
PYTHONPATH=src python3.12 -m expra_engine.export.cli examples/space_pong --target linux --output /tmp/opencode/space-pong-export --no-bytecode --no-debug-launcher --runtime-profile none
```

Result: `Export complete: /tmp/opencode/space-pong-export/space_pong_linux`.
The standalone entry point ran through `create_runtime`, `PygameRuntime.run`,
one frame, UI draw, flip, and quit with an injected backend.

### Release build

Command:

```text
./scripts/build-wheel.sh
./scripts/verify-wheel.sh dist/expra_engine-0.2.7.0-py3-none-any.whl
```

Results: build and embedded wheel verification passed; `verify-wheel.sh`
reported `contents OK: 134 members; no forbidden paths` and `SHA256SUMS OK`.
The generated wheel is `dist/expra_engine-0.2.7.0-py3-none-any.whl` and its
SHA-256 is
`b67cef07b0b85c06a11af9d10b97f248dcd9c63de87a3e3d1131ea606d9fa88b`.

## FINAL POLISH ASSESSMENT

All completion criteria have concrete automated or xvfb evidence for generic
authoring, visual extraction, collision editing, HUD/pause/win, resize,
save/reopen, export, and the standard standalone assembly path. The result is
polished at the tested contract level, but the following claims remain
intentionally unmade:

- No real physical display run or screenshot comparison was completed.
- The environment lacks installed `pygame`, so standalone rendering used an
  injected backend rather than a real display.
- Export used `RuntimeProfile.NONE`; an installed dependency-bundled packaged
  Pygame executable was not verified.
- No packaged-runtime smoke test was possible beyond export staging and the
  injected standard runtime path.

The release wheel and checksum are committed in `dist/SHA256SUMS`.
