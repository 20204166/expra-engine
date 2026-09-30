# Runtime-stack responsibility consolidation audit

> **Read-only audit — no code changed.** Covers the fourteen runtime modules
> below plus the ownership searches required by the consolidation rules.
> Findings are classified HIGH / MEDIUM / LOW; nothing is implemented until
> the user says so.

## Scope

Files under review (all under `src/expra_engine/runtime/`):

- `clock.py` (121)
- `collider.py` (101)
- `dialogue.py` (244)
- `easing.py` (284)
- `event_queue.py` (241)
- `events.py` (120)
- `follow.py` (32)
- `input.py` (242)
- `invoke.py` (87)
- `level_anchor.py` (70)
- `lighting_2d.py` (118)
- `material_component.py` (201)
- `material_lighting.py` (59)
- `normal_mapping.py` (333)

Ownership searches also inspected `core/math_utils.py`,
`runtime/validation.py`, `runtime/visual_components.py`,
`runtime/canvas_effects.py`, `runtime/screen_texture.py`,
`runtime/rendering.py`, `runtime/sequence.py`, and every `_color` /
`_color_dict` / light-bound match across `src/`.

---

## Ownership map

| Responsibility | Implementations | Callers | Canonical owner | Contract differences | Decision |
|---|---|---|---|---|---|
| Coerce `Color \| tuple \| list` → `Color` | `_color` in `visual_components`, `canvas_effects`, `screen_texture`, `lighting_2d`; inline in `material_component` | 5 modules | none (should be `rendering.py`) | identical logic (lighting_2d richer) | **CONSOLIDATE (HIGH)** |
| Serialize `Color` → `[r,g,b,a]` | `_color_dict` in `visual_components`, `canvas_effects`, `screen_texture`; inline in `material_component` | 4 modules | none (should be `rendering.py`) | None-aware vs not (drift) | **CONSOLIDATE (HIGH)** |
| Light parameter bounds (energy/radius/falloff/cone/height) | `Light2DComponent.__init__`; `LightDescriptor.__post_init__` | 2 modules | `rendering.py` | identical table + messages | **CONSOLIDATE (MEDIUM)** |
| Normal-map enum + explicit-requires-texture validation | `MaterialComponent.__init__` + 5 setters; `NormalMapDescriptor.__post_init__` | 2 modules | `normal_mapping.py` | identical rules, stored as `.value` vs enum | **CONSOLIDATE (MEDIUM)** |
| Finite-float validation (reject bool) | `lighting_2d._finite`; `validation.coerce_finite_float` | 1 vs many | `validation.py` | near-identical; `_finite` also rejects `bool` | **CONSOLIDATE (MEDIUM, optional)** |
| Fixed-interval accumulator | `invoke.Repeater.update`; `clock.RuntimeClock.on_idle` | 2 modules | each | function call vs event emission | **KEEP (LOW, note)** |
| Non-empty trimmed string component id | `StreamingAnchorComponent`; `WorldPersistentActorComponent` | 2 classes | each | distinct domain components | **KEEP** |
| Anchor types (`LevelAnchor*`) | `core.level_anchor`; re-exported by `runtime.level_anchor` | world/level callers | `core.level_anchor` | compat re-export | **GOOD (already done)** |

---

## Findings

### 1. Color coercion/serialization duplicated across five modules (HIGH)

The responsibility "coerce a `Color | tuple | list` into a canonical
`rendering.Color`" is implemented as a private `_color` in four runtime
modules with **identical bodies**, plus inline in a fifth:

- `visual_components.py:17-23` — `_color`
- `canvas_effects.py:41-47` — `_color`
- `screen_texture.py:117-123` — `_color`
- `lighting_2d.py:29-45` — `_color` (richer: rejects `bool`/non-numeric with friendlier messages)
- `material_component.py:51,138` — inline `emission_color if isinstance(..., Color) else Color(*...)`

The inverse "serialize a `Color` to `[r,g,b,a]`" is likewise duplicated:

- `visual_components.py:26-29` — `_color_dict` (**None-aware**)
- `canvas_effects.py:50-51` — `_color_dict` (not None-aware)
- `screen_texture.py:126-127` — `_color_dict` (not None-aware)
- `material_component.py:172-177` — inline list literal

The `_color_dict` variants have **already drifted** (None-aware vs not). Five
owners of the same two responsibilities is the exact failure the rule warns
about.

**Consolidation:** add two module-level helpers to `rendering.py` (all five
modules already import `Color` from it):

- `coerce_color(value: Color | tuple[float, ...] | list[float]) -> Color` —
  returns `value` when already a `Color`, otherwise requires 3–4 finite numeric
  channels (rejecting `bool`), and constructs `Color`. Adopt the defensive
  behaviour of `lighting_2d._color` so every site gets clear messages and
  consistent `bool`/non-numeric rejection.
- `color_to_rgba(value: Color) -> list[float]` — `[red, green, blue, alpha]`.
- `color_to_rgba_or_none(value: Color | None) -> list[float] | None` — for the
  optional outline/colour fields.

Then migrate `visual_components`, `canvas_effects`, `screen_texture`,
`lighting_2d`, and `material_component` to import and use them; delete the local
`_color`/`_color_dict` helpers.

**Risk:** LOW. Invalid input still raises `ValueError` (message changes to the
clearer form); valid behaviour is unchanged. Verify against the color/component
tests.

---

### 2. Light parameter bounds table duplicated (MEDIUM)

The exact same bounds and error strings appear in two places for the same
conceptual data (a 2D light):

- `rendering.py:247-256` (`LightDescriptor.__post_init__`)
- `lighting_2d.py:80-89` (`Light2DComponent.__init__`)

Both enforce: `energy ∈ [0,8]`, `radius > 0`, `falloff ∈ [0.1,8]`,
`cone_angle ∈ (0,360]`, `height ∈ [0,1024]`. Because `render_extractor` builds a
`LightDescriptor` from a `Light2DComponent`, the rules are applied twice per
light at runtime and can drift.

**Consolidation:** add `validate_light_bounds(energy, radius, falloff,
cone_angle, height) -> None` to `rendering.py`; call it from both
`LightDescriptor.__post_init__` and `Light2DComponent.__init__` after each
site's finite coercion.

**Risk:** LOW. Pure validation extraction; identical messages preserved.

---

### 3. Normal-map validation duplicated (MEDIUM)

The rule "coerce mode/convention/encoding enums; `DISABLED` → error; `EXPLICIT`
requires a texture id; validate strength and texture id" is implemented in:

- `rendering.py:292-308` (`NormalMapDescriptor.__post_init__`)
- `material_component.py:61-75` (`__init__`) plus the `normal_map_mode` /
  `normal_y_convention` / `normal_encoding` / `normal_texture_id` /
  `normal_strength` setters (lines 82–130)

`MaterialComponent.normal_map_descriptor` then constructs a
`NormalMapDescriptor`, re-running the same validation on already-validated
values. The shared scalar helpers (`validate_normal_strength`,
`validate_normal_texture_id`) already live in `normal_mapping.py`; the enum
coercion + `EXPLICIT`-requires-texture rule does not, so it is copied.

**Consolidation:** extract the enum-coercion core into `normal_mapping.py`,
e.g. `coerce_normal_map_enums(mode, convention, encoding) -> tuple[NormalMapMode,
NormalYConvention, NormalMapEncoding]` (raises the existing "unsupported
normal-map …" error), and have both `NormalMapDescriptor.__post_init__` and
`MaterialComponent.__init__`/setters call it. The `EXPLICIT`-requires-texture
guard remains a small shared predicate where it already is (a one-line check).

**Risk:** LOW–MEDIUM. `MaterialComponent` keeps its `.value`-string storage; only
the validation source is de-duplicated.

---

### 4. `lighting_2d._finite` reimplements `coerce_finite_float` (MEDIUM, optional)

`lighting_2d.py:17-26` (`_finite`) is a near-copy of
`runtime/validation.py::coerce_finite_float` (lines 13–21), differing only in
that `_finite` rejects `bool` up front while `coerce_finite_float` would coerce
`True` → `1.0`.

**Consolidation options:**

- **(a) Harden the canonical owner:** make `coerce_finite_float` reject `bool`
  (aligning with `lighting_2d._finite` and other bool-rejecting validators), then
  have `lighting_2d` import it. This also fixes the latent `True`→`1.0`
  acceptance everywhere.
- **(b) Reuse as-is:** swap `lighting_2d._finite` for `coerce_finite_float`,
  accepting the slight semantic change (bool no longer rejected at this site).

Option (a) is a wider behaviour change (other `coerce_finite_float` callers) and
should be validated against those callers; option (b) is narrower. Recommend (b)
unless bool-rejection matters here, in which case (a) with a focused test.

---

### 5. Fixed-interval accumulator duplicated (LOW, KEEP-leaning)

`invoke.Repeater.update` (`invoke.py:57-68`) and `RuntimeClock.on_idle`
(`clock.py:99-121`) both implement "accumulate `dt`; while `accumulated >=
interval` fire and subtract". The mechanism is shared; the outputs differ
(function call vs `Update` event emission) and `RuntimeClock` layers
pause/time-scale/unscaled-elapsed on top.

**Decision:** KEEP SEPARATE. Extracting a generic "accumulate-and-fire" helper
would save ~4 lines but couple two owners with genuinely different contracts and
lifecycles. Noted for completeness; no action recommended.

---

### Already consolidated (no action)

- `follow.py` → `core.math_utils.lerp_exponential_decay`.
- `invoke.py` → `sequence.Sequence/Wait/Func`.
- `dialogue.py` → `core.safe_expression.evaluate`.
- `collider.py` → `validation.finite_float`; `visual_components` → `finite_float`/`pair_values`.
- `event_queue.py` → `core.utils.camel_to_snake` + `core.errors.BadEventHandlerException`.
- `level_anchor.py` → re-exports `core.level_anchor` (prior cross-owner resolution).
- `normal_mapping.py` → canonical scalar validators (`validate_normal_strength`, `validate_normal_texture_id`) already extracted.

---

## Implementation plan (ordered)

> Run after each step; final gate at the end. No source edits are made yet.

### Step 1 — Color coercion + serialization (HIGH, lowest risk)

1. Add `coerce_color`, `color_to_rgba`, `color_to_rgba_or_none` to
   `src/expra_engine/runtime/rendering.py`.
2. Migrate `visual_components.py`, `canvas_effects.py`, `screen_texture.py`,
   `lighting_2d.py` (replace `_color`/`_color_dict`), and `material_component.py`
   (inline `emission_color` coercion + list serialization) to use them.
3. Delete the local helpers.
4. Verify: `pytest tests/test_visual_components.py tests/test_lighting_2d.py
   tests/test_material_component.py tests/test_canvas_effects.py tests/test_screen_texture.py -q`
   (plus any color/rendering tests), then `ruff check` on changed files.

### Step 2 — Light bounds (MEDIUM)

1. Add `validate_light_bounds(...)` to `rendering.py`.
2. Call it from `LightDescriptor.__post_init__` and `Light2DComponent.__init__`.
3. Verify: `pytest tests/test_rendering.py tests/test_lighting_2d.py -q`.

### Step 3 — Normal-map enum coercion (MEDIUM)

1. Add `coerce_normal_map_enums(...)` to `normal_mapping.py`.
2. Use it in `NormalMapDescriptor.__post_init__` and `MaterialComponent`
   (`__init__` + setters).
3. Verify: `pytest tests/test_normal_mapping.py tests/test_material_component.py -q`.

### Step 4 — `_finite` reuse (MEDIUM, optional; only if option chosen)

1. Per option (a) or (b) above.
2. Verify the validation and lighting tests.

### Step 5 — Final validation gate

- `pytest tests/ -q`
- `ruff check src/expra_engine/runtime`
- scoped `pyright` on changed files
- `git diff --check`

---

## Validation commands (exact)

```bash
python -m pytest tests/test_visual_components.py tests/test_lighting_2d.py tests/test_material_component.py tests/test_canvas_effects.py tests/test_screen_texture.py tests/test_normal_mapping.py tests/test_rendering.py -q
python -m pytest tests/ -q
python -m ruff check src/expra_engine/runtime
git diff --check
```

## Remaining opportunities (not scheduled)

- `_WHITE = Color(...)` sentinel duplicated in `lighting_2d`, `material_component`,
  `canvas_effects` (trivial; would follow Step 1 naturally).
- `Repeater` vs `RuntimeClock` accumulator (Finding 5) — intentionally kept separate.

## Working-tree status

Read-only. No files changed by this audit.
