# Space Pong Dogfood Game

Space Pong is Expra's deliberately small testing game. It is kept in the
repository so engine work is exercised through the real editor and runtime,
not only through isolated unit tests.

## Purpose

Space Pong is the acceptance project for checking that Expra can build and
iterate a polished 2D game through its supported workflow:

```text
open project
  -> create/select entities
  -> add and edit generic components in Inspector
  -> configure visuals and colliders
  -> attach scripts and edit exposed values
  -> preview in the editor
  -> Play / pause / win / Stop
  -> Save / reopen
  -> Export and run the standalone entry point
```

The game is intentionally small: two paddles, a ball, an arena, score/win
feedback, pause/restart behavior, and responsive HUD layout.

## Ownership Rule

Game content belongs in `examples/space_pong/`:

- paddle and ball rules;
- scoring, AI difficulty, and winning score;
- colors, labels, positions, and feedback timings;
- scene composition and project-owned scripts.

Generic engine capabilities belong in Expra:

- component registration and Inspector editing;
- primitive, sprite, text, and collider components;
- renderer-neutral extraction and Pygame rendering;
- runtime UI layout, focus, pointer states, and resize behavior;
- deterministic physics queries and trigger lifecycle;
- editor preview, save/reopen, and export workflow.

Engine code must not branch on `Space Pong`, `Pong`, `Ball`, `Paddle`, project
names, or game-specific labels. If the game exposes a missing generic seam,
fix that seam and add regression tests rather than adding a game special case.

## Layout

```text
examples/space_pong/
  project.json
  scene/main.json
  scripts/space_pong_behaviour.py
  __main__.py
```

The scene includes a generic `Camera` entity so the project is useful for
editor preview and runtime camera acceptance checks.

## Acceptance Checks

Run the focused game tests:

```bash
PYTHONPATH=src python3.12 -m pytest -q tests/test_space_pong.py
```

Run the real editor checks when a display is unavailable through Xvfb:

```bash
xvfb-run -a env PYTHONPATH=src python3.12 -m pytest -q tests/test_editor_ui.py tests/test_editor_render_targets.py
```

The full evidence record is maintained in
`docs/SPACE_PONG_FINAL_REPORT.md`, and multi-engine extraction provenance is
tracked in `docs/POLISH_EXTRACTION_MAP.md`.

## Change Policy

Keep Space Pong small and focused on one polished game loop. Do not add content
or engine features solely for visual novelty. Every engine-facing change should
preserve backward compatibility and add focused edge-case tests for the
behavior it introduces.
