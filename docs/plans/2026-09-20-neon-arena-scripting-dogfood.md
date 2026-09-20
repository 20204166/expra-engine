# Neon Arena Scripting Dogfood Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended by the repository workflow) or execute this plan task-by-task with tests.

**Goal:** Prove Neon Arena runs identically through both its existing legacy RuntimeSystem path and the public project Behaviour scripting path, including real export.

**Architecture:** Keep `NeonArenaGame` as an explicit legacy mode. Add a scripted mode whose scene owns `ScriptComponent`s and whose game-specific rules live in project scripts; the bootstrap selects exactly one mode. Generic Expra systems remain shared and no Neon-specific ownership checks are added to the engine.

**Tech Stack:** Expra `Behaviour`, `BehaviourSystem`, `ScriptComponent`, `ScriptRegistry`, `InputMap`, `EventQueue`, existing Pygame runtime/renderer, `GameExporter`, unittest/pytest.

## File Map

- Modify `examples/neon_arena/game.py`: retain legacy game system and expose shared mode/data helpers only.
- Modify `examples/neon_arena/__main__.py`: select legacy or scripted mode without registering both.
- Add `examples/neon_arena/scripts/player_behaviour.py`: semantic movement with exposed speed and bounds.
- Add `examples/neon_arena/scripts/arena_behaviour.py`: target collision and typed collection event.
- Add `examples/neon_arena/scripts/game_controller.py`: score, win, restart, and event-driven state.
- Add `examples/neon_arena/scripts/events.py`: project event dataclasses.
- Add/update Neon scene/project data: scripted components, input mappings, and mode metadata.
- Modify `tests/test_neon_arena.py`: parity and legacy/scripted lifecycle tests.
- Add exporter/standalone test coverage for the scripted project path.
- Modify only general Expra runtime APIs if tests demonstrate a reusable gap.

## Task 1: Establish explicit modes

- [ ] Add a mode selector in the Neon Arena bootstrap with `legacy` as the compatibility default and `scripted` as the opt-in path.
- [ ] Keep legacy registration exactly as before when scripted mode is disabled.
- [ ] Register `BehaviourSystem` and project `ScriptRegistry` only for scripted mode; never register `NeonArenaGame` in that mode.
- [ ] Add a test asserting each mode registers its intended gameplay owner and never both.

## Task 2: Add project Behaviour scripts

- [ ] Add semantic action constants and map `move_left`, `move_right`, `move_up`, `move_down`, and `restart` to the existing arrow/R physical controls.
- [ ] Implement `PlayerBehaviour` using `Behaviour.input`, `TransformComponent`, and an exposed `speed` field consumed during movement.
- [ ] Implement `ArenaBehaviour` for the existing target proximity reaction and emit `TargetCollected` through `Behaviour.emit`.
- [ ] Implement `GameController` for score, `GameWon`, restart requests, and reset state using the existing engine scene lifecycle.
- [ ] Keep bounds, dt movement, target disablement, score, win state, and restart identical to legacy behavior.

## Task 3: Fill only general API gaps

- [ ] Write failing regression tests for any missing public capability found by the scripts, such as semantic held-action access or typed custom event delivery.
- [ ] Fix the generic Expra API, not Neon code, while preserving existing callers and legacy behavior.
- [ ] Test disabled/removed scripted components and unrelated scripts independently; unrelated scripts must not suppress legacy systems.

## Task 4: Parity and lifecycle tests

- [ ] Run the same deterministic input sequence through legacy and scripted modes.
- [ ] Assert matching player position, score, target state, win state, restart reset, and clean stop.
- [ ] Assert one movement update, one collection, and one win event in scripted mode.
- [ ] Assert Behaviour start, exposed-value application, stop, destroy, and no duplicate cleanup.

## Task 5: Real export verification

- [ ] Export the scripted Neon Arena with the real `GameExporter`.
- [ ] Verify the exported package includes project scripts and resolves `project://` resources.
- [ ] Launch it without editor/Tk imports, drive the existing controls, reach the same win state, and quit cleanly.
- [ ] Retain legacy export coverage and report both mode results separately.

## Verification Commands

- `.venv/bin/pytest tests/test_neon_arena.py tests/test_export_exporter.py -q`
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check src tests examples`
- `.venv/bin/ruff format --check src tests examples`
- Real exporter command used by the Neon Arena export test, followed by standalone launch with the fake/headless Pygame harness.
