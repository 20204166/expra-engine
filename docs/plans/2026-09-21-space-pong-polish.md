# Space Pong Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the generic editor, renderer, runtime UI, physics, and preview seams required to build a polished small 2D game through Expra, then prove them with Space Pong.

**Architecture:** Preserve Expra's `Engine`/`Scene`/`Entity`/`Component`, runtime systems, command stack, renderer contracts, and Tk/Pygame adapter boundary. Add metadata-driven authoring, a shared scene-to-`RenderFrame` extractor, a pure runtime UI tree, a deterministic 2D physics backend, and editor overlays. Space Pong remains project data/scripts only.

**Tech Stack:** Python 3.12, dataclasses, Tk/ttk editor, Pygame runtime adapter, existing pytest suite, JSON project/scene serialization.

---

## File Structure Map

### Create

- `src/expra_engine/core/component_schema.py` — immutable component field metadata and typed edit conversion.
- `src/expra_engine/runtime/visual_components.py` — renderer-neutral primitive, sprite, and text components.
- `src/expra_engine/runtime/render_extractor.py` — scene/component to `RenderFrame` extraction.
- `src/expra_engine/runtime/ui/` — pure UI tree, layout, events, and draw commands.
- `src/expra_engine/runtime/collider.py` — collider component data and supported shape validation.
- `src/expra_engine/runtime/physics_world.py` — deterministic overlap/raycast/trigger backend behind existing physics contracts.
- `examples/space_pong/` — project, scenes, scripts, and assets created through supported project APIs.
- `docs/SPACE_PONG_FINAL_REPORT.md` — concrete dogfood evidence and the required extraction-audit section.
- `tests/test_component_schema.py`, `tests/test_render_extractor.py`, `tests/test_runtime_ui.py`, `tests/test_physics_world.py`, `tests/test_space_pong.py` — focused regression coverage.

### Modify

- `src/expra_engine/core/component.py` — register metadata without changing existing serialization.
- `src/expra_engine/core/entity.py`, `src/expra_engine/core/scene.py` — safe component removal and lookup behavior where required by tests.
- `src/expra_engine/editor/commands.py`, `src/expra_engine/editor/app.py` — undoable generic component edits/add/remove.
- `src/expra_engine/ui/inspector.py` — metadata-driven controls, searchable add/remove, stale selection protection.
- `src/expra_engine/ui/viewport.py` — shared render preview plus editor-only grid/selection/collider overlays and pan/zoom.
- `src/expra_engine/runtime/rendering.py` — minimal text, texture, tint, outline, and nine-slice descriptors/capabilities.
- `src/expra_engine/runtime/pygame_renderer.py` — draw generic render commands and runtime UI commands; retain legacy compatibility.
- `src/expra_engine/runtime/pygame_runtime.py`, `src/expra_engine/runtime/pointer.py` — resize and pointer routing into runtime UI.
- `docs/POLISH_EXTRACTION_MAP.md` — implementation records, tests, evidence, and provenance.
- Space Pong final report document — required extraction-audit section and concrete acceptance evidence.

### Do not modify

- Reference repositories under `/home/btn17/Downloads/exp`, `/home/btn17/Downloads/ursina-master`, `/home/btn17/Downloads/pursuedpybear-canon`, and `/home/btn17/Downloads/MiniPyEngine-main`.
- Expra's canonical runtime ownership boundaries by introducing replacement engines, loops, or physics systems.

## Global Rules

- Write each focused regression test first and run it red before production code.
- Keep serialized components backend-neutral; never store Pygame or Tk objects.
- Use `CommandStack` for editor mutations and reject stale entity/component targets.
- Use stable ordering for equal-depth/equal-distance results.
- Preserve existing tests and JSON shapes unless an additive migration test proves the change.
- Every substantial adaptation updates the parity map with source, behavior, coupling removed, destination, tests, and license status.

## Tasks

### Task 1: Component Metadata and Generic Inspector Authoring

Add typed registry metadata, generic component field controls, remove-component,
duplicate/required policy, stale-selection guards, and undoable edits.

**Files:** `src/expra_engine/core/component_schema.py`, `src/expra_engine/core/component.py`, `src/expra_engine/ui/inspector.py`, `src/expra_engine/editor/commands.py`, `tests/test_component_schema.py`, `tests/test_editor_ui.py`, `tests/test_editor_commands.py`.

- [ ] **Step 1: Write failing schema tests.** Cover a float, int, bool, enum, color/tuple field, invalid input rejection, read-only metadata, and a component with a required `TransformComponent`.
- [ ] **Step 2: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_component_schema.py`; verify the new schema import/API fails.**
- [ ] **Step 3: Implement `PropertyDescriptor(name, label, value_type, default, editable, enum_values, minimum, maximum)` and `ComponentTypeSpec(name, cls, fields, required_types)`.** Conversion must reject non-finite numbers, clamp nothing silently, and return the original value on rejected editor input.
- [ ] **Step 4: Register `TransformComponent` metadata and preserve `component_from_dict`/`registered_component_types` behavior.** Add a metadata lookup that returns an immutable tuple and raises a clear error for unknown types.
- [ ] **Step 5: Run schema and existing component tests; commit `feat: add component property metadata`.**
- [ ] **Step 6: Write failing Inspector tests for generic fields, duplicate add rejection, remove-component undo/redo, required-component protection, invalid values, and selection removal during a pending edit.**
- [ ] **Step 7: Run the focused Inspector tests red.** The failure must identify the missing generic field/remove behavior rather than a fixture error.
- [ ] **Step 8: Implement Inspector rendering from `ComponentTypeSpec`, a searchable component chooser, a remove action per component section, and callbacks carrying `(entity_id, component_type, field_name, value)`.
- [ ] **Step 9: Route callbacks through `CommandStack`; resolve the entity and component again at execution time so stale selections become no-ops with no mutation.**
- [ ] **Step 10: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_component_schema.py tests/test_editor_ui.py tests/test_editor_commands.py`; commit `feat: make registered components editable`.**

### Task 2: Renderer-Neutral Visual Components and Extraction

Add primitive/sprite/text components and a single extraction path shared by Tk
preview and Pygame rendering, including deterministic ordering and malformed-data
handling.

**Files:** `src/expra_engine/runtime/visual_components.py`, `src/expra_engine/runtime/render_extractor.py`, `src/expra_engine/core/component.py`, `src/expra_engine/runtime/rendering.py`, `tests/test_render_extractor.py`, `tests/test_entity.py`, `tests/test_scene.py`.

The extraction boundary is intentionally small:

```python
def extract_render_frame(scene: Scene, *, elapsed: float = 0.0) -> RenderFrame:
    """Convert registered scene visuals into backend-neutral render data."""
```

- [ ] **Step 1: Write failing serialization tests for `PrimitiveComponent(kind, width, height, radius, fill, outline, outline_width, layer, visible)`, `SpriteComponent(asset, tint, width, height, layer, visible)`, and `TextComponent(text, font, size, color, max_width, align, layer, visible)`.** Include empty text, disabled component, zero/negative dimensions, unknown primitive kind, and round-trip JSON.
- [ ] **Step 2: Run the focused tests red.**
- [ ] **Step 3: Implement dataclass components with finite-value validation and additive `to_dict`/`from_dict` payloads.** Keep colors as Expra tuples/`Color`, not Pygame values.
- [ ] **Step 4: Write failing extractor tests for transform composition, visibility, phase/layer ordering, equal-depth stable ordering, unsupported/malformed components, and legacy entities remaining renderable.
- [ ] **Step 5: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_render_extractor.py`; verify extraction is absent or incomplete.
- [ ] **Step 6: Implement `extract_render_frame(scene, elapsed=0.0)` that reads only registered components and emits `RenderItem`s.** It must skip disabled/malformed visuals deterministically, preserve entity iteration order as the final tie-breaker, and never import Pygame/Tk.
- [ ] **Step 7: Register the new component types and add an editor-independent component-to-render contract test.**
- [ ] **Step 8: Run rendering, entity, scene, and extractor tests; commit `feat: extract generic scene visuals`.**

### Task 3: Text, Materials, Nine-Slice, and Pygame Draw Adapter

Extend only the missing backend-neutral descriptors and implement Pygame text,
tint/opacity, layered outline/glow approximation, and existing nine-slice
geometry consumption.

**Files:** `src/expra_engine/runtime/rendering.py`, `src/expra_engine/runtime/pygame_renderer.py`, `src/expra_engine/runtime/visual_components.py`, `tests/test_runtime_rendering.py`, `tests/test_pygame_renderer.py`, `tests/test_render_extractor.py`.

- [ ] **Step 1: Write failing contract tests for optional `texture_id`, tint, outline color/width, blend mode, text draw data, and nine-slice draw data.** Verify defaults preserve the current constructors and invalid alpha/width/radius values fail.
- [ ] **Step 2: Run focused rendering tests red.**
- [ ] **Step 3: Add immutable descriptors and capability flags without adding backend imports to `runtime/rendering.py`.** Keep unsupported capabilities explicit rather than silently emulating textures.
- [ ] **Step 4: Write failing fake-surface tests for text alignment/wrapping, empty/multiline text, alpha, off-screen/partial primitives, layer order, and two-layer outline/glow approximation.
- [ ] **Step 5: Implement Pygame adapter methods that consume only descriptors and injected font/resource providers.** Use deterministic fallback font loading; never hardcode Space Pong strings.
- [ ] **Step 6: Implement nine-slice drawing by consuming `NineSliceGeometry.resolve()` rectangles; do not duplicate the geometry algorithm in the renderer.
- [ ] **Step 7: Run renderer/extractor tests and the full Pygame renderer suite; commit `feat: render generic text and styled primitives`.**

### Task 4: Runtime UI Tree, Layout, and Interaction

Build pure `GameCanvas`/`UIElement` models with anchors, safe-area/reference
resolution layout, text/panel/button commands, states, focus, pointer capture,
and resize behavior; adapt them in Pygame without Tk.

**Files:** `src/expra_engine/runtime/ui/__init__.py`, `src/expra_engine/runtime/ui/elements.py`, `src/expra_engine/runtime/ui/layout.py`, `src/expra_engine/runtime/ui/events.py`, `src/expra_engine/runtime/pygame_renderer.py`, `src/expra_engine/runtime/pygame_runtime.py`, `src/expra_engine/runtime/pointer.py`, `tests/test_runtime_ui.py`, `tests/test_pygame_runtime.py`.

The pure UI boundary is:

```python
class GameCanvas(UIElement):
    def layout(self, viewport: Viewport, safe_area: Insets = Insets()) -> LayoutResult: ...
    def hit_test(self, point: tuple[float, float]) -> UIElement | None: ...
    def draw_commands(self) -> tuple[UIDrawCommand, ...]: ...
```

- [ ] **Step 1: Write failing pure-model tests for a root canvas, child panel/label/button, anchor layout, minimum/preferred size, safe-area insets, and logical-to-pixel resize resolution.** Include zero-size roots and extreme aspect ratios.
- [ ] **Step 2: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_runtime_ui.py`; verify the runtime UI package is missing.**
- [ ] **Step 3: Implement immutable `Rect`, `Insets`, `LayoutSpec`, and `LayoutResult` resolution using reference size plus current viewport.** Anchor edges remain stable under resize; stretched elements consume the safe area.
- [ ] **Step 4: Write failing state tests for normal, hover, pressed, focused, disabled buttons; hidden elements; destroyed focus targets; pointer capture; and deterministic hit-test order.**
- [ ] **Step 5: Implement `UIElement`, `GameCanvas`, `Panel`, `Label`, `Button`, and `UIEvent` as pure models.** Reuse existing control/focus/pointer semantics and keep action callbacks outside the renderer.
- [ ] **Step 6: Write failing draw-command tests for labels, panels, buttons, nine-slice panels, and state-specific styles; verify runtime modules contain no Tk import.**
- [ ] **Step 7: Implement renderer-neutral UI draw commands and Pygame translation.** Route Pygame pointer/keyboard events to the UI root before gameplay actions when a modal/focused control owns them.
- [ ] **Step 8: Run runtime UI, Pygame runtime, input, pointer, focus, geometry, control, and nine-slice tests; commit `feat: add renderer-backed runtime UI`.**

### Task 5: Collider Authoring and Deterministic Physics Backend

Add supported collider component fields, editor configuration, deterministic
AABB/circle overlap/raycast behavior, trigger lifecycle tracking, and tests for
contact/disabled/removed/deterministic cases.

**Files:** `src/expra_engine/runtime/collider.py`, `src/expra_engine/runtime/physics_world.py`, `src/expra_engine/runtime/physics.py`, `src/expra_engine/core/component.py`, `src/expra_engine/ui/inspector.py`, `tests/test_physics_world.py`, `tests/test_runtime_physics.py`, `tests/test_component_schema.py`.

The backend stays behind existing result contracts:

```python
class PhysicsWorld2D:
    def overlap(self, body_id: str, *, include_triggers: bool = True) -> tuple[str, ...]: ...
    def raycast(self, origin: tuple[float, float], direction: tuple[float, float], distance: float) -> HitResult2D: ...
    def step_triggers(self) -> tuple[TriggerEvent, ...]: ...
```

- [ ] **Step 1: Write failing validation tests for rectangle/circle shapes, positive dimensions/radius, offset, solid/trigger, enabled, layer/mask, and unsupported values.** Expose only fields the backend implements.
- [ ] **Step 2: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_physics_world.py tests/test_runtime_physics.py`; verify the backend is missing.**
- [ ] **Step 3: Implement `ColliderComponent` with canonical serialization and metadata.** Use explicit shape names and reject negative/zero geometry rather than normalizing silently.
- [ ] **Step 4: Write failing world tests for exact contact, initial overlap, fast segment/raycast movement, disabled/destroyed colliders, layer/mask filtering, nearest deterministic hit, and enter/stay/exit lifecycle.**
- [ ] **Step 5: Implement `PhysicsWorld2D` with stable entity insertion order and simple broadphase-free queries first.** Return existing `HitResult2D`; emit `TriggerEvent` only for active pairs and clear pairs when a collider disappears.
- [ ] **Step 6: Add Inspector collider fields and editor-only outline data sourced from the component.** Do not put preview state in serialized physics data.
- [ ] **Step 7: Run physics, serialization, Inspector, and existing runtime tests; commit `feat: add editable deterministic 2d colliders`.**

### Task 6: Shared Editor Viewport Preview

Render scene visuals from the same extraction data used by the runtime, then add
Tk-only grid, selection, collider overlays, pan/zoom, frame-selected, and
frame-scene behavior.

**Files:** `src/expra_engine/ui/viewport.py`, `src/expra_engine/ui/editor_window.py`, `src/expra_engine/runtime/render_extractor.py`, `tests/test_editor_render_targets.py`, `tests/test_editor_ui.py`, `tests/test_render_extractor.py`.

- [ ] **Step 1: Write failing viewport tests for primitive/sprite/text extraction, actual colors, layer order, off-screen clipping, selected entity highlight, removed selection, and malformed visual data.**
- [ ] **Step 2: Run `PYTHONPATH=src python3.12 -m pytest -q tests/test_editor_render_targets.py tests/test_editor_ui.py`; verify the shared preview path is absent.**
- [ ] **Step 3: Add a Tk adapter that consumes `RenderFrame`/draw data and keeps grid, axes, labels, and selection as editor overlays.** Preserve existing callbacks and no-scene behavior.
- [ ] **Step 4: Write failing interaction tests for pan, bounded zoom, frame-selected, frame-scene, resize, and collider-outline visibility without changing scene data.**
- [ ] **Step 5: Implement viewport camera state and interaction using the existing camera projection contract; do not reimplement runtime extraction or make Canvas the exported renderer.**
- [ ] **Step 6: Run editor UI/render-target, extractor, and live/headless viewport tests where available; commit `feat: preview runtime visuals in editor viewport`.**

### Task 7: Space Pong Through the Real Workflow

Create/open the project, construct entities/components/scripts through the GUI,
run HUD/pause/win/resize flows, stop/edit/save/reopen/export/run standalone, and
capture evidence without engine-specific branches.

**Files:** `examples/space_pong/project.json`, `examples/space_pong/scenes/main.json`, `examples/space_pong/scripts/space_pong_behaviour.py`, `tests/test_space_pong.py`, `docs/POLISH_EXTRACTION_MAP.md`, `docs/SPACE_PONG_FINAL_REPORT.md`.

- [ ] **Step 1: Write failing project tests that open the project, discover registered components/scripts, and verify scene data contains only generic components and project-owned script values.**
- [ ] **Step 2: Run the Space Pong test red because the project does not exist.**
- [ ] **Step 3: Create the project through Expra project APIs/editor commands: background/arena primitives, paddles, ball, colliders, camera, HUD UI elements, and script components.** Keep paddle speed, colors, winning score, star positions, and AI difficulty in project data/scripts.
- [ ] **Step 4: Add script tests for paddle movement, deterministic bounce/score/win, pause/resume, hit feedback through timeline/tween, restart, and resize-stable UI.**
- [ ] **Step 5: Run headless project/runtime tests and capture editor/Inspector/runtime/pause/win evidence through the supported launch path.**
- [ ] **Step 6: Exercise Stop, edit, Save, close/reopen, Export, and standalone run; record exact commands and results in the parity map/final report.**
- [ ] **Step 7: Commit `feat: add Space Pong editor dogfood project`.**

### Task 8: Full Verification, Provenance, and Release

Run focused/full suites, compile/diff/build/export checks, finish the parity map
and final report, and publish only after evidence supports the completion claim.

**Files:** `docs/POLISH_EXTRACTION_MAP.md`, the Space Pong final report, `scripts/build-wheel.sh` outputs, and focused/full test logs.

- [ ] **Step 1: Run focused suites for component schemas, editor UI/commands, extraction, rendering, runtime UI, physics, viewport, project workflow, export, and Space Pong.**
- [ ] **Step 2: Run the full suite, `python3.12 -m compileall -q src tests examples`, `git diff --check`, and relevant export verification.** Record unavailable tools honestly; do not treat missing Ruff/Pyright/Mypy as passes.
- [ ] **Step 3: Update the parity map implementation records with exact source symbols, coupling removed, destination, adapted/new tests, license status, rendered evidence, and explicit rewritten-from-scratch justifications.**
- [ ] **Step 4: Add the required `POLISH / MULTI-ENGINE EXTRACTION AUDIT` section to the Space Pong final report.** State whether all completion criteria have concrete evidence; list any residual gaps instead of claiming polish prematurely.
- [ ] **Step 5: Review the full staged diff, run the canonical wheel build and `scripts/verify-wheel.sh`, then commit `build: publish polished Space Pong workflow`.**
