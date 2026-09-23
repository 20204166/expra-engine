# Sprite/Texture Editor Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Edit and Play share real sprite/texture rendering while keeping Tk editor overlays and renderer-neutral scene data.

**Architecture:** Extend `SpriteComponent` into the existing `RenderItem` source-region/offset/flip contract. Reuse `PygameRenderer` and `PygameResourceProvider` for an optional transparent offscreen editor frame, then display that frame as a Tk image beneath existing overlays. Missing optional Pygame or assets use the current geometry fallback.

**Tech Stack:** Python 3.12, dataclasses, Tk/Ttk, optional Pygame, pytest, Xvfb.

---

## File Map

- Modify `src/expra_engine/runtime/visual_components.py` for additive static-sprite fields.
- Modify `src/expra_engine/core/component.py` for Inspector metadata defaults.
- Modify `src/expra_engine/runtime/render_extractor.py` for static-sprite mapping.
- Modify `src/expra_engine/runtime/pygame_renderer.py` for transparent clearing.
- Modify `src/expra_engine/ui/viewport.py` for the optional offscreen pixel layer and fallback.
- Create `src/expra_engine/ui/editor_pixel_renderer.py`, `src/expra_engine/ui/viewport_render_target.py`, and `src/expra_engine/ui/viewport_overlays.py` to keep optional backend and editor seams isolated.
- Modify `src/expra_engine/ui/editor_window.py` and `src/expra_engine/editor/project_workflow.py` for resource-service lifecycle.
- Modify `tests/test_render_extractor.py`, `tests/test_pygame_renderer.py`, and `tests/test_editor_render_targets.py` with red-green regression coverage.
- Create `tests/test_editor_texture_rendering.py` for injected editor pixel/fallback seams.
- Create `docs/specs/2026-09-23-sprite-texture-editor-rendering-design.md` and keep this plan uncommitted because the user prohibited commits.

## Execution Rules

- Use TDD: write one focused failing test, run it, implement the smallest passing change, then run the focused regression set.
- Do not add a second animation owner, resource resolver, thumbnail scheduler, or texture draw implementation.
- Do not import Pygame from renderer-neutral modules or serialize surfaces, providers, plans, or Tk images.
- Keep alpha hit testing, full region UI, and advanced asynchronous thumbnails deferred.
- Do not commit or push.

## Tasks

### Task 1: Add Static Sprite Semantics

**Files:** `visual_components.py`, `component.py`, `render_extractor.py`, and their existing tests.

- [x] Add failing serialization/schema/extraction tests for `region`, `offset`, `centered`, `flip_h`, and `flip_v`.
- [x] Run the focused tests and confirm they fail because static sprites omit the new fields.
- [x] Add validated fields with additive JSON defaults and map them to `MaterialDescriptor.source_region` and `RenderItem` sprite fields.
- [x] Run component, extractor, animation, and scene tests to green.

### Task 2: Make Backend Clearing Configurable

**Files:** `pygame_renderer.py`, `tests/test_pygame_renderer.py`.

- [x] Add a failing test proving `clear_color=None` clears an alpha-capable surface without changing default runtime dark clearing.
- [x] Run the test red.
- [x] Add the optional constructor argument and the smallest surface-clear helper; preserve existing fake-backend behavior and default.
- [x] Run all Pygame renderer tests to green.

### Task 3: Add Editor Offscreen Pixel Presentation

**Files:** `viewport.py`, `tests/test_editor_texture_rendering.py`, `tests/test_editor_render_targets.py`.

- [x] Add failing injected-backend tests for render-surface creation, Tk image conversion, retained image references, and fallback when Pygame is unavailable.
- [x] Run them red.
- [x] Add an injectable/lazy Pygame backend that renders the canonical `RenderFrame` with the editor camera and converts the surface to a Tk `PhotoImage`.
- [x] Keep grid, selection, labels, colliders, markers, click bounds, and existing Tk geometry fallback intact.
- [x] Run focused editor and renderer tests to green.

### Task 4: Wire Project Resource Lifecycle

**Files:** `editor_window.py`, `project_workflow.py`, `tests/test_editor_texture_rendering.py`.

- [x] Add `test_open_project_replaces_viewport_resources` proving opening a project supplies its `ResourceService` and closing clears it.
- [x] Run `PYTHONPATH=src pytest -q tests/test_editor_texture_rendering.py::test_open_project_replaces_viewport_resources`; record the expected assertion failure before production edits.
- [x] Add the constructor/setter wiring without creating a new resolver or changing project serialization.
- [x] Run project, editor, asset, and renderer tests to green.

### Task 5: Verify the Integrated Slice

- [x] Run `PYTHONPATH=src pytest -q tests/test_render_extractor.py tests/test_pygame_renderer.py tests/test_editor_render_targets.py tests/test_editor_texture_rendering.py`.
- [x] Run the complete suite with `PYTHONPATH=src pytest -q`.
- [x] Run `xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m pytest -q tests/test_editor_ui.py`.
- [x] Run `git diff --check` and inspect `git status --short`; report optional-Pygame acceptance separately if the dependency remains absent.
