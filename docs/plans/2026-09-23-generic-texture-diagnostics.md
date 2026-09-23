# Generic Texture Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable structured texture diagnostic API and real-PNG project fixture that verify the existing asset-to-pixel path for any Expra project.

**Architecture:** Extend `PygameResourceProvider` with per-call failure status, then add a thin runtime orchestration module that reuses project resolution, extraction, provider decoding, renderer drawing, and the existing editor pixel bridge. Keep Blacksite as an integration caller and add a project-independent temporary fixture.

**Tech Stack:** Python 3.12, dataclasses, pytest, Pygame optional runtime backend, Tk/Xvfb editor tests.

---

## File Map

- Create `src/expra_engine/runtime/texture_diagnostics.py` for immutable report types and orchestration.
- Modify `src/expra_engine/runtime/pygame_renderer.py` to expose the provider's last failure stage without changing `__call__` behavior.
- Modify `src/expra_engine/runtime/__init__.py` to export the public report types and function.
- Create `tests/support/texture_project.py` for the generic temporary-project factory.
- Create `tests/fixtures/texture_probe.png` as a small real PNG fixture.
- Create `tests/test_texture_diagnostics.py` for generic success and failure coverage plus Blacksite dogfood coverage.
- Modify `tests/test_editor_texture_rendering.py` only where shared diagnostic coverage needs to replace Blacksite-specific assumptions.

## Task 1: Lock the Public Report Contract

**Files:**
- Test: `tests/test_texture_diagnostics.py`
- Create: `src/expra_engine/runtime/texture_diagnostics.py`

- [x] **Step 1: Write failing report/API tests**

Define tests for immutable stage/report values, canonical asset IDs, successful generic reports, missing sprite matches, missing resources, invalid PNG bytes, and invalid arguments. Assert failures return `ok=False`, `failed_stage`, and detail instead of raising.

- [x] **Step 2: Run the focused tests and confirm the expected import/API failure**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_texture_diagnostics.py`; expect collection to fail because the new module and symbols do not exist.

- [x] **Step 3: Implement the immutable report types and validation skeleton**

Use frozen, slotted dataclasses with tuple fields. `diagnose_texture()` must validate `Project`, `Scene`, `RenderContext`, `pygame_module`, and the parsed `ResourceId`, then return a failed report for pipeline failures.

- [x] **Step 4: Re-run the focused tests and record the next failing stage**

Run the same command; the import succeeds and the first missing pipeline stage becomes the expected failure.

## Task 2: Add Provider Failure Evidence

**Files:**
- Modify: `src/expra_engine/runtime/pygame_renderer.py`
- Test: `tests/test_pygame_renderer.py`

- [x] **Step 1: Add failing tests for provider failure status**

Assert a failed metadata lookup reports `resolve`, a failed byte read reports `read`, a failed Pygame decode reports `decode`, and a successful call clears the previous failure.

- [x] **Step 2: Run the provider tests and confirm they fail**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_pygame_renderer.py -k 'failure or decode or read or resolve'`; expect missing status evidence.

- [x] **Step 3: Add minimal per-call failure state**

Reset status at the start of `PygameResourceProvider.__call__`, set stable stage/detail values in existing exception branches, and expose a read-only `last_failure` property. Preserve current logging, cache keys, and return values.

- [x] **Step 4: Run the provider tests until green**

Run the focused command again and confirm all selected tests pass without changing existing provider behavior.

## Task 3: Implement the Diagnostic Pipeline

**Files:**
- Modify: `src/expra_engine/runtime/texture_diagnostics.py`
- Modify: `src/expra_engine/runtime/__init__.py`
- Test: `tests/test_texture_diagnostics.py`

- [x] **Step 1: Add the extraction and resolution assertions**

Use the real `Project` and `Scene` fixture. Assert the report includes the matched entity ID, `extract`, `resolve`, and `read` stages, mount name, physical path, and byte size.

- [x] **Step 2: Run the test and confirm the missing implementation stage**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_texture_diagnostics.py -k 'generic or resolve or missing'`; expect failure at the first unimplemented report stage.

- [x] **Step 3: Implement canonical extraction, resolution, and read stages**

Parse the requested logical ID, find matching `SpriteComponent` entities, call `extract_render_frame(scene)`, select matching `RenderItem`s, call `project.resource_service()`, resolve through its resolver, and read through `ResourceService.read_bytes()`.

- [x] **Step 4: Add decode and renderer pixel stages**

Create one `PygameResourceProvider` and one alpha-capable offscreen surface, decode through the provider, render only the selected items through `PygameRenderer`, and record texture size, cache key, backend type, and non-transparent output bounds. Use provider failure status to map read/resolve/decode failures.

- [x] **Step 5: Add optional editor presentation**

When `image_master` is supplied, call `render_editor_frame_to_tk_image()` with the same provider and selected frame. Record the final image dimensions or return an `editor_presentation` failure report.

- [x] **Step 6: Export the public API and run focused tests**

Export `TextureDiagnosticStage`, `TextureDiagnosticReport`, and `diagnose_texture` from `expra_engine.runtime`, then run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_texture_diagnostics.py` and confirm green.

## Task 4: Add a Project-Independent Real PNG Fixture

**Files:**
- Create: `tests/fixtures/texture_probe.png`
- Create: `tests/support/texture_project.py`
- Test: `tests/test_texture_diagnostics.py`

- [x] **Step 1: Add the fixture and factory test**

Use a real PNG with stable visible pixels. The factory must call `Project.create()`, import the fixture into `assets/probe.png`, create a scene with an origin-centered `SpriteComponent`, save it, and return `(project, scene, asset_id)`.

- [x] **Step 2: Run the factory test and confirm fixture/project failures are visible**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_texture_diagnostics.py -k fixture`; verify the test exercises the temporary project rather than Blacksite paths.

- [x] **Step 3: Assert real decoded and rendered pixels**

Use the installed Pygame backend, a `160x120` viewport, and a camera that includes the origin. Assert the report is successful and its output bounds and decoded dimensions are non-empty.

## Task 5: Dogfood the API in Blacksite

**Files:**
- Modify: `tests/test_texture_diagnostics.py`
- Review: `tests/test_editor_texture_rendering.py`

- [x] **Step 1: Add the Blacksite diagnostic acceptance test**

Load Blacksite normally, collect distinct visible `SpriteComponent.asset` IDs from its scene, and call `diagnose_texture()` for each with a broad camera covering the configured playfield. Assert each report succeeds without naming a specific Blacksite entity in the reusable factory.

- [x] **Step 2: Run the Blacksite test and fix only integration mismatches**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_texture_diagnostics.py -k blacksite`; preserve the existing EDIT/PLAY movement test and do not edit either user-owned scene JSON file.

- [x] **Step 3: Run the focused renderer/editor suites**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_pygame_renderer.py tests/test_editor_texture_rendering.py tests/test_texture_diagnostics.py` and resolve regressions in the canonical path rather than adding test-only bypasses.

## Task 6: Final Verification and Review

**Files:**
- Review all changed implementation, tests, spec, and plan files.

- [x] **Step 1: Run the full test suite**

Run `PYTHONPATH=src .venv/bin/python -m pytest -q`; record the exact pass/fail result.

- [x] **Step 2: Run the Xvfb editor suite**

Run `xvfb-run -a env PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_editor_ui.py tests/test_editor_texture_rendering.py tests/test_texture_diagnostics.py`; record the exact result.

- [x] **Step 3: Run static and diff checks**

Run `PYTHONPATH=src .venv/bin/ruff check src/expra_engine/runtime/pygame_renderer.py src/expra_engine/runtime/texture_diagnostics.py src/expra_engine/runtime/__init__.py tests/test_pygame_renderer.py tests/test_texture_diagnostics.py tests/support/texture_project.py`, then `git diff --check`.

- [x] **Step 4: Self-review the implementation against the design**

Confirm the API reuses the existing resolver/provider/renderer/editor bridge, reports every required stage and evidence field, keeps Blacksite-specific paths out of the generic fixture, and leaves the two user-owned scene edits untouched. Do not commit or push unless explicitly requested.

## Plan Self-Review

- Spec coverage: scope stages map to Task 3; structured failures map to Tasks 1-3; real generic fixture maps to Task 4; Blacksite dogfood maps to Task 5; verification maps to Task 6.
- Ownership: resource resolution remains `Project.resource_service()`; extraction remains `extract_render_frame()`; decoding remains `PygameResourceProvider`; drawing remains `PygameRenderer`; editor presentation remains `editor_pixel_renderer`.
- Placeholder scan: no unresolved steps or placeholder markers remain.
- Type consistency: report names, provider `last_failure`, test factory return shape, and all commands are consistent across tasks.
