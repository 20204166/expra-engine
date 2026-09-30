# Render-stack responsibility consolidation audit

> **Read-only audit — no code changed.** Covers the seven modules the user
> scoped, plus the ownership searches required by the consolidation rules.
> Recommendations are classified HIGH / MEDIUM / LOW; nothing here is
> implemented until the user says so.

## Scope

Files under review:

- `src/expra_engine/runtime/rendering.py` (638)
- `src/expra_engine/runtime/render_pipeline.py` (372)
- `src/expra_engine/runtime/render_extractor.py` (330)
- `src/expra_engine/runtime/render_diagnostics.py` (43)
- `src/expra_engine/core/pixel_perfect.py` (86)
- `src/expra_engine/core/engine.py` (891)
- `src/expra_engine/core/color.py` (150)

Ownership searches also inspected `core/math_utils.py`, `core/utils.py`,
`core/bounds.py`, `runtime/validation.py`, `ui_model/geometry.py`,
`core/scene/document_codec.py`, `core/scene/scene_instance.py`,
`design/tokens.py`, and every consumer of `rendering.Color` and
`core.color.Color` across `src/`, `tests/`, and the repo root.

---

## Ownership map

| Responsibility | Implementations | Callers | Canonical owner | Contract difference | Decision |
|---|---|---|---|---|---|
| RGBA color value | `core/color.py::Color`; `runtime/rendering.py::Color` | core.Color → only `tests/test_core_color.py`; rendering.Color → ~28 modules | `runtime/rendering.py::Color` | clamp vs reject; `r/g/b/a` vs `red/green/blue/alpha`; conversions/ops only in core | **CONSOLIDATE (HIGH)** |
| Current-time source | `core/utils.py::get_time` (perf_counter); `engine.py` `time.monotonic()` | engine tick vs play/pause/update | `core/utils.py::get_time` | perf_counter vs monotonic on the same `_last_update` field | **CONSOLIDATE (MEDIUM)** |
| Scene clone via codec round-trip | `engine._copy_scene` inline `json.dumps(to_dict)`; `document_codec.to_json` + `from_document_data` | engine only | `document_codec` | deterministic + kind-aware vs ad-hoc + Scene-only | **CONSOLIDATE (MEDIUM)** |
| Finite-float validation | `core/math_utils.finite_float`; inline in `pixel_perfect`, `color._clamp01` | pixel_perfect, color | `core/math_utils.finite_float` | partial overlap (bool/positivity checks are extra) | **LOW / optional** |
| Axis-aligned rectangle | `Bounds2D` (min/max), `Rect` (origin+size, float), `Viewport` (origin+size, int) | world/UI/render respectively | each in its own layer | coordinate rep + precision + use-case differ | **KEEP SEPARATE** |
| Draw-order sort key | `render_item_order_key` only | `RenderFrame.ordered_items`, `RenderOrder.from_item` | `runtime/rendering.py` | none — already shared | **GOOD (no action)** |
| Parent/child 2D pose compose | `core/math_utils.compose_2d_pose` only | `Transform.compose`, `Scene.world_pose` | `core/math_utils` | none — already shared | **GOOD (no action)** |

---

## Findings

### 1. Duplicate `Color` type — one is dead code (HIGH)

Two `Color` classes own the "RGBA value in [0,1]" responsibility with
**different field names and different validation semantics**:

- `src/expra_engine/core/color.py:26` — fields `r, g, b, a`; **clamps**
  out-of-range values (`_clamp01`, line 18); rich API (`from_hex`,
  `from_hsv`, `from_rgba8`, `rgba8`, `hsv`, `with_alpha`, `lerp`, `tint`,
  `shade`). Documented "adapted from Ursina's color.py".
- `src/expra_engine/runtime/rendering.py:186` — fields
  `red, green, blue, alpha`; **rejects** non-finite/out-of-range values
  (`__post_init__`, lines 192–196); no conversions or operations.

**Evidence that `core.color.Color` is dead:** a repo-wide search for
`core.color`, `from_hsv`, `from_hex`, `from_rgba8`, `.rgba8`, `.with_alpha(`,
`.lerp(`, `.tint(`, `.shade(` finds **zero production consumers** — the only
file that references `core.color.Color` is its own test
`tests/test_core_color.py`. `design/tokens.py` stores hex **strings**, not
`Color` objects. Meanwhile `rendering.Color` is imported by ~28 modules
(visual components, materials, lighting, screen texture, canvas effects, all
`pygame_*` renderers, editor pixel renderer, normal-map UI, etc.).

The clamp-vs-reject divergence is exactly the "two owners drift apart" failure
the consolidation rule warns about: both types claim to be the canonical color,
and they already disagree.

**Recommendation — Option A (preferred): delete the dead owner.**

- Delete `src/expra_engine/core/color.py` and `tests/test_core_color.py`.
- `rendering.Color` becomes the single canonical `Color`. Its reject-on-
  construct semantics are the correct contract for backend-neutral render data
  (fail fast at the boundary). No production behavior changes.

**Option B (only if the user wants to retain the color utilities):** fold the
conversion/design ops into `rendering.Color` and delete `core/color.py`. The
`lerp`/`tint`/`shade` ops must clamp internally (they already produce in-range
results by construction); keep the constructor rejecting. This is a larger
design change and should not be done merely because the utilities "might be
needed someday" — there is no current consumer.

**Risk:** LOW for A (dead code). For B, MEDIUM (new surface area on the
canonical type with no consumers to exercise it).

---

### 2. Time source duplicated in `engine.py` (MEDIUM)

`core/utils.py::get_time()` is the documented canonical time source
("All runtime timers use this function so delta-time is consistent") and
returns `perf_counter()`.

`core/engine.py` bypasses it in three places, using `time.monotonic()`
directly against the **same `_last_update` field** that `tick()` feeds via
`get_time()`:

- `engine.py:365` (`play`) — `self._last_update = time.monotonic()`
- `engine.py:382` (`pause` → resume) — `self._last_update = time.monotonic()`
- `engine.py:427` (`update`) — `now = time.monotonic()`
- `engine.py:460` (`tick`) — `now = get_time()`  ← the only correct one

On current CPython/Linux both clocks map to `CLOCK_MONOTONIC`, so the runtime
impact is benign **today**, but this is a genuine ownership violation that has
already drifted (`update()` and `tick()` disagree). If `get_time()` is ever
changed (e.g. a wall-clock debug switch), the engine's dt would silently mix
two bases.

**Consolidation:** replace the three `time.monotonic()` calls with `get_time()`
(already imported at `engine.py:34`), and drop the now-unused `import time`
(`engine.py:9`).

**Risk:** LOW. `get_time()` is imported and returns `perf_counter()`; no caller
semantics change.

---

### 3. `engine._copy_scene` reimplements the document codec (MEDIUM)

`engine._copy_scene` (`engine.py:836–840`) clones the edit scene with

```python
Scene.from_dict(json.loads(json.dumps(scene.to_dict())))
```

This duplicates the round-trip responsibility already owned by
`core/scene/document_codec.py`:

- `document_codec.to_json()` (line 72) serializes deterministically
  (`sort_keys=True, separators=(",", ":"), allow_nan=False`).
- `document_codec.from_document_data()` (line 92) reconstructs **kind-aware**:
  `Scene` vs `Level` vs `World`.

The inline version differs in two material ways:

1. **Non-deterministic** — `json.dumps(...)` without `sort_keys`/`separators`,
   and `allow_nan` not forced off.
2. **Not kind-aware** — `Scene.from_dict(...)` would drop `level_metadata` if
   the edit scene were a `Level` (a `Scene` subclass). Today the runtime edit
   scene is a plain `Scene`, so this is latent rather than live.

**Consolidation:** delegate to the codec, e.g. add a `clone_document(document)`
helper in `document_codec.py` (`from_document_data(to_json(document), copy_data=True)`)
and have `_copy_scene` call it, or call the two codec functions directly from
`_copy_scene`. This removes the ad-hoc JSON round-trip and gains kind-awareness
for free.

**Risk:** LOW–MEDIUM. `to_json` normalizes via `json` (sort keys) and
`from_document_data` reconstructs the same model; existing runtime scene-copy
tests (`tests/test_pygame_runtime.py`, scene-stack tests) must stay green.

---

### 4. Hand-rolled finite-float checks in core (LOW / optional)

`core/math_utils.py::finite_float()` (line 8) is the canonical "reject
non-finite float" owner; `runtime/validation.py` re-exports it and adds
`coerce_finite_float` (line 13).

Two core modules hand-roll the same check instead of reusing it:

- `core/pixel_perfect.py:52–59` — inline `math.isfinite` + bool-rejection +
  positivity for `pixels_per_unit`.
- `core/color.py::_clamp01` (lines 18–22) — inline `math.isfinite` (moot once
  Finding 1 deletes the file).

The overlap is **partial**: both also reject `bool` and (in pixel_perfect)
check positivity, which `finite_float` does not do. Reuse would be cosmetic
rather than a correctness fix.

**Decision:** KEEP / defer. Not worth a change on its own; if Finding 1 deletes
`core/color.py`, only the pixel_perfect case remains and it is clearer as-is.

---

### 5. `Rect` vs `Viewport` vs `Bounds2D` — KEEP SEPARATE

Three axis-aligned rectangle types with genuinely different contracts:

- `core/bounds.py::Bounds2D` — min/max corners, float, spatial queries
  (`contains(x, y)`, `intersects`, `expand`, center/size).
- `ui_model/geometry.py::Rect` — origin+size, float, logical layout,
  non-negative dims, no containment helpers.
- `runtime/rendering.py::Viewport` — origin+size, **int**, pixel space,
  positive dims, `right`/`bottom`/`contains(point)`.

Combining them would erase the int-vs-float (pixel vs logical) and
minmax-vs-origin-size distinctions that each layer relies on. Per the rules,
specialized contracts with different precision and use-cases stay separate.

Two minor observations, **not** recommended for change:

- `contains()` exists in both `Viewport` (tuple arg) and `Bounds2D` (two
  scalars) with different signatures — unification would be coupling for
  trivial duplication.
- `runtime/rendering.py` already imports `Rect` from `ui_model` (line 22) for
  `NineSliceDescriptor`, i.e. a runtime→ui_model dependency. Flagged as a
  layering note; moving `Rect` is out of scope for a consolidation edit.

---

### 6. Already correctly consolidated (no action)

- **Draw order** — `render_item_order_key` (`rendering.py:567`) is the single
  owner of the phase/layer/depth/insertion sort, consumed by both
  `RenderFrame.ordered_items` and `RenderOrder.from_item`. Its docstring states
  the intent explicitly; no drift.
- **Pose composition** — `Transform.compose` and `Scene.world_pose` both
  delegate to `core/math_utils.compose_2d_pose`; the trig is not duplicated.
- **Finite-float** — `finite_float` lives once in `core/math_utils` and is
  re-exported (not copied) by `runtime/validation`.
- **`RenderDiagnostics`** (`render_diagnostics.py`) is a clean, single-owner
  state machine with no duplication.

---

## Implementation plan (ordered)

> Run after each step; final gate at the end. No source edits are made yet.

### Step 1 — Time source (MEDIUM, lowest risk, do first)

1. In `src/expra_engine/core/engine.py`, replace `time.monotonic()` with
   `get_time()` at lines 365, 382, and 427.
2. Remove `import time` (line 9) if nothing else uses it.
3. Verify: `python -m pytest tests/test_pygame_runtime.py tests/test_scene_instance.py -q`,
   plus any engine state-transition tests, then `python -m ruff check src/expra_engine/core/engine.py`.

### Step 2 — Scene clone via codec (MEDIUM)

1. Add `clone_document(document)` to
   `src/expra_engine/core/scene/document_codec.py`:
   `from_document_data(to_json(document), copy_data=True)`.
2. Change `Engine._copy_scene` (line 836) to call it; keep the `None` guard.
3. Verify existing clone-behaviour tests
   (`tests/test_pygame_runtime.py`, scene-stack/isolation tests) and add a
   regression that a `Level` clone preserves `level_metadata`.

### Step 3 — Dead `Color` removal (HIGH value, depends on Step 0 of user decision)

1. Delete `src/expra_engine/core/color.py` and `tests/test_core_color.py`.
2. Confirm no imports remain: `rg "core.color|core import Color"`.
3. Verify: full `tests/` suite + `python -m ruff check src/expra_engine`.

### Step 4 — (Optional, only if user chooses Option B) Unify color utilities

Only if the user wants to keep hex/hsv/lerp capabilities: fold them into
`runtime/rendering.Color`, then delete `core/color.py`. Not recommended without
a consumer.

### Step 5 — Final validation gate

- `python -m pytest tests/ -q`
- `python -m ruff check src/expra_engine/core src/expra_engine/runtime`
- `python -m pyright` (scoped to changed files) or the repo's configured check
- `git diff --check`

---

## Validation commands (exact)

```bash
python -m pytest tests/test_pygame_runtime.py tests/test_scene_instance.py -q
python -m pytest tests/ -q
python -m ruff check src/expra_engine/core/engine.py src/expra_engine/core/scene/document_codec.py src/expra_engine/runtime/rendering.py
git diff --check
```

## Remaining opportunities (not scheduled)

- `core/engine.py` is 891 lines (over the 700-line soft threshold): state +
  scene stack + systems + behaviours + world lifecycle + dispatch root. A
  later split is a LOW-VALUE/HIGH-RISK broad refactor; deferred.
- `runtime/rendering.py → ui_model.geometry.Rect` layering note (Finding 5).

## Working-tree status

Read-only. No files changed by this audit.
