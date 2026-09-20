# Non-Tk Playable Game Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and export a genuinely playable non-Tk Neon Arena game using a Pygame/SDL runtime adapter.

**Architecture:** Keep `Engine` renderer-neutral. Add Pygame-backed runtime systems for input, timing/window lifecycle, and primitive 2D rendering; package only runtime dependencies and validate the exported launcher in a dummy SDL environment.

**Tech Stack:** Python, Pygame, SDL2, existing Expra runtime events, Linux venv export, unittest/pytest.

---

## File Map

- Create `src/expra_engine/runtime/pygame_runtime.py`: Pygame event polling, window lifecycle, frame loop, and injected backend seam.
- Create `src/expra_engine/runtime/pygame_renderer.py`: primitive entity/HUD renderer driven by runtime events.
- Modify `src/expra_engine/runtime/__init__.py`: export public runtime adapters.
- Modify `src/expra_engine/pyproject.toml` or root `pyproject.toml`: declare the runtime dependency separately from editor dependencies.
- Modify `src/expra_engine/export/plan.py`: carry a runtime profile/package selection.
- Modify `src/expra_engine/export/packager.py`: install runtime packages without editor dependencies and preserve non-zero launcher failures.
- Modify `src/expra_engine/export/exporter.py`: stage runtime-only engine modules and profile metadata.
- Modify `src/expra_engine/export/verify.py`: reject editor/Tk/Ursina/Panda3D imports while allowing the selected game runtime backend.
- Create `examples/neon_arena/project.json`, `examples/neon_arena/scenes/main.json`, and `examples/neon_arena/__main__.py`: real game project.
- Create `tests/test_pygame_runtime.py`, `tests/test_pygame_renderer.py`, `tests/test_neon_arena.py`, and extend export tests.

## Task Sequence

### Task 1: Runtime API and failing tests

- [ ] Add tests for injected Pygame events, quit handling, fixed frame calls, and cleanup.
- [ ] Define the test seam as `PygameRuntime(engine, pygame_module, clock, surface_factory)`; the fake module exposes `QUIT`, `KEYDOWN`, `KEYUP`, `event.get()`, `display.set_mode()`, and `quit()`.
- [ ] Assert the first frame calls `engine.tick(dt)` and a quit event causes `run()` to return while calling `pygame.quit()` exactly once.
- [ ] Run the focused tests and confirm they fail because the adapter does not exist.
- [ ] Add the smallest runtime adapter skeleton and public exports.
- [ ] Run the focused tests and commit the runtime seam.

### Task 2: Pygame input and loop

- [ ] Implement event polling, key state, window creation, `Engine.tick(dt)`, and shutdown.
- [ ] Use an injectable Pygame module/clock/display seam so tests run with `SDL_VIDEODRIVER=dummy` or fakes.
- [ ] Add tests proving `QUIT` stops the loop and frame timing reaches the engine.
- [ ] Run runtime tests and commit.

The runtime loop must follow this order per frame: poll events, update input
state, call `engine.tick(dt)`, dispatch renderer systems, flip the display, and
clock-limit the next frame. A game callback may request stop without importing
Tk or editor modules.

### Task 3: Primitive renderer and HUD

- [ ] Add failing renderer tests for transform-to-screen mapping, player/target primitives, score text, and win text.
- [ ] Implement renderer subscription to scene/update/render lifecycle without adding renderer ownership to `Engine`.
- [ ] Run renderer tests and commit.

Use a `RenderFrame` data object containing the active scene, score, and status;
the renderer consumes it in `on_render`. Draw only rectangles/circles/lines and
font text. Keep screen coordinates and arena bounds in renderer configuration,
not in `Engine` or entity serialization.

### Task 4: Neon Arena game

- [ ] Add failing behavior tests for keyboard movement bounds, target collection, score, win, and restart scene reset.
- [ ] Create the sample project and implement its runtime systems using only public Expra runtime APIs.
- [ ] Run game behavior tests with the dummy SDL backend and commit.

The game system owns transient score/targets/status and reads the runtime input
adapter. It mutates only the runtime scene copy. Restart calls `engine.stop()`
then `engine.play()` after resetting transient state; saved scene JSON remains
unchanged. The deterministic test places one target on the player's path and
expects `score == 1` and `status == "won"` after the target is collected.

### Task 5: Runtime-only export profile

- [ ] Add failing export tests showing the current wheel pulls editor dependencies and exported launchers can mask failures.
- [ ] Add a runtime package profile that installs Pygame and the runtime engine without `ttkbootstrap`, Tk, editor modules, Ursina, or Panda3D.
- [ ] Ensure Linux launchers use `set -e` and `pipefail` in debug mode so game errors return non-zero.
- [ ] Verify export manifests and forbidden-import checks, then commit.

The profile must be explicit in `ExportPlan`, not inferred from arbitrary game
imports. Package installation must use `--no-deps` for the monolithic engine
wheel or stage a runtime-only package, then install only the declared Pygame
runtime dependency. The verifier scans staged game/runtime Python files and
fails with the relative path and import name for every forbidden import.

### Task 6: End-to-end exported game

- [ ] Export `examples/neon_arena` for Linux with the runtime profile.
- [ ] Launch it with `SDL_VIDEODRIVER=dummy`, run a deterministic smoke path, and assert a completion report.
- [ ] Launch it under `xvfb-run` for visible window evidence and inspect the rendered surface.
- [ ] Run the full test, lint, type-check, wheel-build, and export verification commands.
- [ ] Commit the sample/export fixtures and push only after all evidence is recorded.

Required evidence commands:

```bash
SDL_VIDEODRIVER=dummy ./builds/Neon_Arena_linux/Neon_Arena_debug.sh
./scripts/verify-wheel.sh dist/expra_engine-<version>-py3-none-any.whl
pytest -q
ruff check src tests examples
mypy src
pyright
```

The exported smoke run must import the bundled runtime without `PYTHONPATH`,
write a deterministic report, and return non-zero if the game cannot start.
