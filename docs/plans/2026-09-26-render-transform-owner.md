# Render Transform Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the render transform used for drawing and culling canonical across the runtime renderer and editor viewport.

**Architecture:** Add `RenderItem.visual_transform`, selecting `sprite_transform` for textured items and `world_transform` otherwise. Migrate runtime draw, visibility bounds, and editor geometry to this property; retain `world_transform` for depth ordering and `sprite_transform` as an explicit lower-level property.

**Tech Stack:** Python 3.12, renderer-neutral dataclasses, Pygame, pytest.

---

## File Map

- Modify `src/expra_engine/runtime/rendering.py`: add the canonical property and use it in visibility bounds.
- Modify `src/expra_engine/runtime/pygame_renderer.py`: draw with the property.
- Modify `src/expra_engine/ui/viewport.py`: use it for item geometry, selection, and hit testing.
- Extend `tests/test_runtime_rendering.py`, `tests/test_pygame_renderer.py`, and `tests/test_editor_texture_rendering.py`.

### Task 1: Specify Transform Semantics

**Files:** Modify `tests/test_runtime_rendering.py`.

- [x] **Step 1: Add tests before production changes.** Assert textured items apply sprite offsets, untextured items use their world transform, and a textured non-`sprite` primitive is culled using its textured visual position.

```python
item = RenderItem(
    "textured-rectangle",
    PrimitiveDescriptor("rectangle", size=(2.0, 2.0)),
    Transform(position=(6.0, 0.0, 0.0)),
    material=MaterialDescriptor(texture_id="assets://shape.png"),
    sprite_offset=(-2.0, 0.0),
)
assert item.visual_transform.position == (4.0, 0.0, 0.0)
assert item.is_visible(context)
```

- [x] **Step 2: Prove the tests are red.** Run `pytest tests/test_runtime_rendering.py -q`. Expected: the new tests fail because `RenderItem.visual_transform` does not exist.

### Task 2: Add the Canonical Runtime Property

**Files:** Modify `src/expra_engine/runtime/rendering.py`.

- [x] **Step 1:** Add a read-only `visual_transform` property returning `self.sprite_transform if self.material.texture_id is not None else self.world_transform`.
- [x] **Step 2:** Change `_projected_bounds()` to use `visual_transform`; keep `is_visible()` depth checks based on `world_transform`.
- [x] **Step 3:** Run `pytest tests/test_runtime_rendering.py -q`. Expected: all runtime contract tests pass.

### Task 3: Migrate Runtime and Editor Callers

**Files:** Modify `src/expra_engine/runtime/pygame_renderer.py` and `src/expra_engine/ui/viewport.py`.

- [x] **Step 1:** Replace the renderer's local transform conditional with `item.visual_transform`.
- [x] **Step 2:** Replace viewport transform conditionals in render-item drawing, projected corners, selection outlines, and hit testing with `item.visual_transform`.
- [x] **Step 3:** Extend `tests/test_pygame_renderer.py` to assert a textured non-`sprite` primitive is positioned with the same visual transform. Extend `tests/test_editor_texture_rendering.py` to assert viewport hit testing uses the canonical textured position.
- [x] **Step 4:** Run `pytest tests/test_runtime_rendering.py tests/test_pygame_renderer.py tests/test_editor_texture_rendering.py -q`. Expected: all pass, including existing offset, rotation, and culling coverage.

### Task 4: Final Checks

- [x] Run Ruff on the three implementation files and three test files.
- [x] Run `git diff --check` and review that world-depth ordering and serialized component data are unchanged.
