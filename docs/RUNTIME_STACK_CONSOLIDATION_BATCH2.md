# Runtime-stack responsibility consolidation audit (batch 2)

> **Read-only audit — no code changed.** Covers the twelve runtime modules
> below plus ownership searches. Findings classified HIGH / MEDIUM / LOW;
> nothing implemented until the user says so.

## Scope

Files under review (all under `src/expra_engine/runtime/`):

- `screen_texture.py` (417)
- `script_component.py` (10)
- `script_registry.py` (112)
- `sequence.py` (74)
- `smooth_follow.py` (37)
- `system.py` (62)
- `texture_diagnostics.py` (483)
- `tilemap.py` (96)
- `timeline.py` (181)
- `trail.py` (66)
- `transform_interpolation.py` (316)
- `tween.py` (42)

Ownership searches also inspected `core/math_utils.py`,
`runtime/validation.py`, `runtime/rendering.py`, `runtime/easing.py`,
`runtime/follow.py`, `runtime/invoke.py`, `core/script_component.py`,
`ui_model/geometry.py`, and `runtime/visual_components.py`.

---

## Summary verdict

This batch is largely clean. Most modules already delegate to canonical owners
(`lerp_exponential_decay`, `Color.from_value`/`to_list`, `coerce_finite_float`,
`core.script_component`). One clear duplication remains (Finding 1), plus a
low-value repeated validation pattern (Finding 2).

---

## Ownership map

| Responsibility | Implementations | Callers | Canonical owner | Contract difference | Decision |
|---|---|---|---|---|---|
| Scalar lerp + shortest-arc angle lerp | inline in `transform_interpolation._interpolate`; `core.math_utils.lerp`/`lerp_angle` | 1 | `core.math_utils` | identical math | **CONSOLIDATE (HIGH)** |
| "finite non-negative dt" validation | inline in `sequence`, `timeline`, `tween`, `trail`, `smooth_follow`, `invoke`, `clock`, `follow` | 8 | none (could be `validation.py`) | same predicate, near-identical messages | **LOW / optional** |
| Exponential follow | `follow.exponential_follow` (stateless); `smooth_follow.SmoothFollow` (stateful) | 2 | both → `math_utils.lerp_exponential_decay` | stateful vs stateless API | **KEEP** |
| Time-accumulator scheduler | `Sequence`, `Timeline`, `Repeater`, `Tween` | 4 | each | step-list vs delay/duration/loop vs interval vs scalar | **KEEP** |
| `ScriptComponent` re-export | `runtime.script_component` → `core.script_component` | runtime callers | `core.script_component` | compat re-export | **GOOD (already done)** |

---

## Findings

### 1. `transform_interpolation._interpolate` reimplements `math_utils.lerp` + `lerp_angle` (HIGH)

`_interpolate` (`transform_interpolation.py:43-58`) hand-rolls both the scalar
lerp and the shortest-arc angle interpolation that `core/math_utils.py` already
owns:

- local `lerp(a, b) = a + (b - a) * alpha` (line 44-45) is exactly
  `math_utils.lerp` (line 23).
- the rotation arc (`transform_interpolation.py:49-54`):
  ```python
  delta = (current.rotation - previous.rotation + 180.0) % 360.0 - 180.0
  rotation = previous.rotation + delta * alpha
  ```
  is exactly `math_utils.lerp_angle(previous.rotation, current.rotation, alpha)`
  (line 35-38) — same `% 360 - 180` shortest-arc formula.

This is a textbook "two owners will drift" case: if the arc convention ever
changes (e.g. sign of rotation), `transform_interpolation` and every other
`lerp_angle` consumer would disagree.

**Consolidation:** import `lerp`/`lerp_angle` from `core.math_utils` and reduce
`_interpolate` to compose them. No behavior change (the formulas are identical);
the module already depends on `core` (`TransformComponent`, `Scene`).

**Risk:** LOW. Pure math substitution; covered by interpolation tests.

---

### 2. "Finite non-negative dt" validation duplicated across eight modules (LOW)

The exact predicate "reject non-finite or negative delta" is inlined in:

- `sequence.py:39-40`, `timeline.py:112-117`, `tween.py:32-33`,
  `trail.py:39-40`, `smooth_follow.py:22-23`, `invoke.py:58-59`,
  `clock.py:110-111`, `follow.py:23-24`.

Each raises `ValueError` with a message like "must be finite and non-negative".
`runtime/validation.py` already owns `coerce_finite_float`; a sibling
`coerce_non_negative_finite(value, name)` would give one owner for this rule.

**Decision:** LOW value / optional. The checks are 1–2 lines with slightly
differing messages ("dt", "delta", "duration"); extracting adds a helper with
little payoff unless the drift (e.g. some check `<= 0`, others `< 0`) is worth
locking down. Recommend deferring, or applying only if the user wants it.

---

### 3. `SmoothFollow` vs `exponential_follow` — KEEP

`follow.exponential_follow` (stateless function) and
`smooth_follow.SmoothFollow` (stateful object) both target
`math_utils.lerp_exponential_decay` (already the single mechanism owner). The
two APIs serve different call styles (functional vs held state); the math is
already consolidated. No action.

---

### 4. `Tween` default easing vs `easing.linear` — KEEP

`tween.py:15` defaults `easing` to `field(default=lambda t: t)`, which is
identical to `easing.linear`. Importing `easing.linear` for the default would be
cleaner but adds a module dependency for a one-character default. Not worth it.

---

### 5. `Sequence` / `Timeline` / `Repeater` / `Tween` — KEEP

Four time-accumulating schedulers with genuinely different contracts (ordered
step list with waits; delay/duration/loop + callbacks as a `RuntimeSystem`;
repeating interval; scalar progress). The shared "accumulate time" mechanic is
trivial and not worth extracting — combining them would erase their distinct
lifecycles (e.g. `Timeline.stop()` clears, `Sequence.reset()` rewinds).

---

### Already consolidated (no action)

- `script_component.py` → re-exports `core.script_component`
  (`ScriptComponent`, `UnresolvedScriptComponent`); canonical owner in core,
  same pattern as `level_anchor`.
- `smooth_follow.py` and `follow.py` → `math_utils.lerp_exponential_decay`.
- `screen_texture.py` → `coerce_finite_float` (as `_finite`),
  `Color.from_value`/`to_list`, `render_phase_from_value` (single owner).
- `system.py` → canonical `RuntimeSystem` base protocol.
- `tilemap.py`, `trail.py`, `script_registry.py` → self-contained, no intra-batch
  duplication.

### Dependency note (not a consolidation edit)

`texture_diagnostics.py` imports `PygameRenderer`/`PygameResourceProvider` at
module top (line 13), so importing the diagnostics module pulls in the pygame
backend. It is deliberately a backend-probing module, but the lazy-import bridge
used for `editor_pixel_renderer` (line 449-452) suggests the same pattern could
apply here if headless import weight ever matters. Flagged only.

---

## Implementation plan (ordered)

> Bounded: only Finding 1 is scheduled; Finding 2 is optional.

### Step 1 — `_interpolate` → `math_utils.lerp` + `lerp_angle` (HIGH)

1. Add `from expra_engine.core.math_utils import lerp, lerp_angle` to
   `transform_interpolation.py`.
2. Rewrite `_interpolate` to use them (drop the local `lerp` closure and the
   inline arc formula).
3. Verify: `pytest tests/test_transform_interpolation.py -q` (or the file that
   covers interpolation), then `ruff check` + `pyright` on the file.

### Step 2 — (Optional) shared non-negative-delta validator (LOW)

Only if the user wants the drift locked down:

1. Add `coerce_non_negative_finite(value, name)` to `runtime/validation.py`.
2. Migrate the eight call sites.
3. Verify the validation/sequence/timeline/tween/trail/follow/clock/invoke tests.

### Step 3 — Final gate

- `pytest tests/ -q`
- `ruff check src/expra_engine/runtime`
- scoped `pyright` on changed files
- `git diff --check`

---

## Validation commands (exact)

```bash
python -m pytest tests/test_transform_interpolation.py tests/test_sequence.py tests/test_timeline.py tests/test_tween.py tests/test_smooth_follow.py tests/test_follow.py -q
python -m pytest tests/ -q
python -m ruff check src/expra_engine/runtime
git diff --check
```

## Working-tree status

Read-only. No files changed by this audit.
