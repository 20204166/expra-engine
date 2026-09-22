# Audio2D Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate renderer-neutral 2D spatial audio into Expra without adding a playback backend or duplicating audio, physics, transform, scene, or asset ownership.

**Architecture:** `AudioStreamPlayer2DComponent` and `AudioListener2DComponent` remain serialized configuration. `Audio2DWorld` resolves authoritative world poses, listener selection, bus routing, and spatial mix. A built-in `Audio2DSystem` owns transient states and emits backend-neutral playback requests through Engine lifecycle events.

**Tech Stack:** Python, dataclasses, pytest, Expra `RuntimeSystem`, `Scene` JSON serialization, existing `AudioMixer`/`AudioClip`/`ResourceService` contracts.

---

## File Map

- Modify `src/expra_engine/runtime/audio_2d.py`: validation hardening, canonical `AudioClip` gain use, world pose default, runtime system.
- Modify `src/expra_engine/core/component.py`: canonical audio component registration and Inspector metadata.
- Modify `src/expra_engine/core/scene/scene.py`: authoritative parent-composed simulation pose query.
- Modify `src/expra_engine/core/engine.py`: create, register, expose, and lifecycle-manage `Audio2DSystem`.
- Modify `src/expra_engine/runtime/__init__.py`: export audio contracts and runtime system.
- Keep `tests/test_audio_2d.py` as the supplied focused source behavior suite.
- Create `tests/test_audio_2d_integration.py`: registration, serialization, hierarchy, edge-case, and Engine lifecycle coverage.

## Task 1: Registration and canonical transform seam

- [x] Add failing tests for both component registry entries, schema fields, full Scene JSON round-trip, and parent-composed `Scene.world_pose()`.
- [x] Run `EXPRA_PYTHON=.venv/bin/python .venv/bin/pytest -q tests/test_audio_2d.py tests/test_audio_2d_integration.py`; confirm failures are missing registration/system/world-pose behavior.
- [x] Implement `_register_audio_components()` with `PropertyDescriptor` metadata and call it from registry access/deserialization.
- [x] Implement `Scene.world_pose(entity_id)` with deterministic parent traversal, authoritative `TransformComponent` values, identity fallback, and cycle detection.
- [x] Re-run focused tests and existing scene/entity/component-schema coverage.

## Task 2: Spatial contracts and runtime owner

- [x] Add failing tests for disabled sources/listeners, deterministic listener selection, current/clear operations, fallback, rotation, distance boundaries, panning, gain, invalid inputs, and transient non-serialization.
- [x] Implement `Audio2DWorld` against `Scene.world_pose()` while retaining injected pose and area-bus resolvers; use `AudioClip.effective_volume()` for source/master/bus gain.
- [x] Implement `Audio2DSystem` as a `RuntimeSystem`: reconcile active scene sources, autoplay, advance state, expose play/seek/stop/pause/state/request APIs, and clean scene-scoped state on lifecycle events.
- [x] Add the system to `Engine` without adding another clock or scene hierarchy; export public audio names from `runtime/__init__.py`.

## Task 3: Verification and final audit

- [x] Run focused audio tests first, then physics/Area, transform/hierarchy, scene lifecycle, asset, component, and runtime-system tests.
- [x] Run the full suite, `compileall`, configured Ruff/Mypy/Pyright checks, and `git diff --check`.
- [x] Search for duplicate mixer/listener ownership, audio overlap math, local-only audio transforms, serialized runtime handles, fake duration/completion logic, and stale scene state.
- [x] Review meaningful changed-line counts and report backend status, parity, warnings, limitations, and unmodified user files.
