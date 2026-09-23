# Rendering Residual Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute this plan task-by-task with test-first checkpoints.

**Goal:** Close the five confirmed rendering/fallback correctness findings from the four-reviewer patch audit.

**Architecture:** Keep the renderer-neutral contracts unchanged at their boundaries. Validate integer pixel regions in the schema, calculate visibility from transformed corners, resolve nine-slice source patches without destination outset, and fail closed before Tk receives an incomplete Pygame image.

**Tech Stack:** Python 3.12, pytest, Pygame 2.6.1, Tk/Xvfb.

## Files

- Modify `src/expra_engine/runtime/rendering.py` for transformed visibility bounds.
- Modify `src/expra_engine/core/component_schema.py` and the sprite schema registration for integer regions.
- Modify `src/expra_engine/runtime/pygame_renderer.py` for safe clearing/backend checks, point outlines, and nine-slice source geometry.
- Modify `src/expra_engine/ui/editor_pixel_renderer.py` for point-outline capability gating.
- Extend `tests/test_render_extractor.py`, `tests/test_component_schema.py`, `tests/test_pygame_renderer.py`, `tests/test_editor_texture_rendering.py`, and the relevant nine-slice tests.

## Tasks

### 1. Reproduce residuals

- [x] Add one failing test per finding: rotated edge visibility, fractional region rejection, nonzero-outset source bounds, point-outline fallback, and clear/partial-backend fallback.
- [x] Run only those tests and confirm each fails for the reported reason.

### 2. Fix visibility and schema boundaries

- [x] Project the four corners of the transformed rectangle whenever item or camera rotation is nonzero; use the resulting screen AABB for `is_visible()`.
- [x] Add `tuple_integer: bool = False` to `PropertyDescriptor`; reject non-integral tuple parts before minimum checks.
- [x] Enable it only on the four-field sprite region descriptor.

### 3. Fix backend and nine-slice failure paths

- [x] Make `_clear_surface()` return success and set `_draw_failed` when fill/draw clearing fails.
- [x] Mark `_draw_failed` when `render()` has no surface or no `pygame.draw`.
- [x] Reject outlined points in `frame_textures_available()`.
- [x] Build nine-slice source patches from a geometry copy with zero outset; keep destination outset unchanged.

### 4. Verify and document

- [x] Run focused tests, full pytest, Xvfb UI tests, static checks, and `git diff --check`.
- [x] Update `PATCH-20260923-001-review.md` only after evidence confirms the five findings are fixed.
