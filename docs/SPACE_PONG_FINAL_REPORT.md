# Space Pong Task 7 Final Report

**Scope:** Task 7 only, after `44b0fa7`. Task 8 release/build work was not
performed.

## Delivered

- `examples/space_pong/project.json` is a schema 1 project with project-owned
  input bindings and `__main__.py` entry point.
- `examples/space_pong/scenes/main.json` contains only generic transforms,
  primitives, text, colliders, and a project-owned `ScriptComponent`.
- `examples/space_pong/scripts/space_pong_behaviour.py` uses `PhysicsWorld2D`,
  `Timeline`, `Tween`, and renderer-neutral runtime UI. Paddle speed, ball
  speed, winning score, AI difficulty, colors, positions, and labels are project
  data or script data.
- `examples/space_pong/__main__.py` assembles the normal `Engine`,
  `ScriptRegistry`, `PygameRenderer`, `PygameRuntime`, render extractor, camera,
  and UI path.

## Verification

Focused project/runtime suite:

```text
PYTHONPATH=src python3.12 -m pytest -q tests/test_space_pong.py
7 passed
```

Related regression suites:

```text
PYTHONPATH=src python3.12 -m pytest -q \
  tests/test_project_workflow.py tests/test_neon_arena.py tests/test_runtime_ui.py \
  tests/test_render_extractor.py tests/test_physics_world.py tests/test_export.py \
  tests/test_export_exporter.py
97 passed
```

The first TDD run was intentionally red before project creation:
`tests/test_space_pong.py` reported 5 failures because
`examples/space_pong/project.json` did not exist.

## Editor Evidence

Real Tk interaction was available through `/usr/bin/xvfb-run`.

Open, edit, undo, play, pause, resume, stop, save, and reopen command:

```text
xvfb-run -a env PYTHONPATH=src python3.12 - <<'PY'
... EditorWindow(Project.load("examples/space_pong")) ...
PY
```

Observed output:

```json
{"entities": 9, "opened": "Space Pong", "paused": "paused", "reopened": ["Space Pong", 9], "resumed": "play", "saved": true, "stopped": "edit"}
```

Inspector-specific interaction selected `space-pong-controller`, changed the
exposed `winning_score` from 3 to 5, changed the left collider height from 12
to 14, verified both changes were undoable, then restored and saved the original
scene. Observed output:

```json
{"collider_height": 14.0, "restored_and_saved": true, "script_value": 5, "selected": "space-pong-controller", "undo_available": true}
```

The editor preview consumes the existing shared `extract_render_frame` path;
the project scene contains primitive, text, and collider data for that preview.

## Runtime And Export Evidence

The standalone source entry point was exercised by
`test_space_pong_standalone_entry_point_runs_the_standard_runtime_path` with an
injected backend. It ran `create_runtime`, `PygameRuntime.run`, renderer start,
one frame, UI draw commands, display flip, and quit handling without opening a
real display.

The real export CLI was run with no bytecode and no external runtime profile:

```text
PYTHONPATH=src python3.12 -m expra_engine.export.cli examples/space_pong \
  --target linux --output /tmp/opencode/space-pong-export \
  --no-bytecode --no-debug-launcher --runtime-profile none
```

Result:

```text
Export complete: /tmp/opencode/space-pong-export/space_pong_linux
```

The export contains the project manifest, scene, script, entry point, manifests,
and Linux runtime bundle. The focused export test also verifies the staged
project files with an injected packager.

## POLISH / MULTI-ENGINE EXTRACTION AUDIT

### Boundary

Space Pong-specific behavior is project-owned. Expra owns only generic project
loading, component registration, rendering extraction, runtime UI layout and
input routing, deterministic collider queries, engine lifecycle, and export
orchestration. No reference repository was modified.

### Provenance

This patch contains no copied reference implementation or bundled reference
assets. Existing Expra contracts and the previously recorded parity map informed
the project integration. License status for the new project-owned code is not
applicable.

### Acceptance Record

| Criterion | Evidence | Status |
|---|---|---|
| Create/open generic project | `Project.load`, editor xvfb output, 9-entity scene | Pass |
| Generic visuals/colliders/scripts | Scene inventory test and Inspector output | Pass |
| Runtime HUD and score/win | Runtime test, text components, UI draw path | Pass |
| Pause/resume/restart | Runtime test and editor output | Pass |
| Deterministic bounce and hit feedback | Focused behavior tests | Pass |
| Resize-stable UI | `GameCanvas` reference-resolution test | Pass |
| Save/reopen | Project workflow test and editor output | Pass |
| Export | Real Linux CLI output and export test | Pass |
| Standalone runtime path | Injected-backend standard runtime test | Pass, headless |

### Residual Gaps

- A real display run was not claimed; the standalone test uses the supported
  injected backend because this environment has no installed `pygame` module.
- The real export used `RuntimeProfile.NONE`, so an installed packaged Pygame
  executable was not claimed. The project entry point and source runtime path
  are covered; full dependency-bundled release verification belongs to Task 8.
- Visual screenshot artifacts were not generated. Concrete command output and
  test evidence are recorded above.
