# Expra Engine Consolidation Audit

**Date:** 2026-09-28
**Source version:** Expra 0.5.4.0
**Audited commit:** `4723b25d89f00948d2766454b686a70e41884016`
**Supplemental audit baseline:** `32abb1b`
**Mode:** Read-only source and test inspection; no implementation changes made.

## Scope and Method

The initial pass audited `src/expra_engine/core/`, `src/expra_engine/runtime/`
(including `runtime/ui/`), `src/expra_engine/filesystem/`,
`src/expra_engine/editor/`, and `src/expra_engine/export/`. The requested
`runtim/` path was treated as a typo for `runtime/`. A supplemental pass covered
the remaining `coordinators/`, `design/`, `messages/`, `schema/`, `ui_model/`,
and `ui/` packages, `observability.py`, and top-level CLI/bootstrap modules.
Generated protobuf bindings were treated as generated output; their source
schemas are under `schemas/`.

The audit searched for repeated validation, path confinement, cloning,
serialization, diagnostic formatting, resource access, lifecycle, and export
failure-handling responsibilities. Candidate callers and related tests were
spot-checked. This was a static audit; tests and runtime probes were not run.

The worktree was already dirty during the audit. Findings reflect the checked-out
working tree, including in-progress editor changes; they are not claims that
those unrelated changes are committed. `runtime/visual_components.py` appeared
as modified during the audit after the initial status check; it was not changed
by this task. The Markdown report is the only file added by this task.

## Summary

The strongest first-pass opportunities were narrowly scoped: exact duplicate
World-session path construction; repeated project-script resource validation;
repeated Entity behaviour-eligibility policy; and duplicate project-root
containment checks. Those APPLY findings have now been implemented. The wider
pass found a lower-level owner question for finite-number math shared by runtime,
UI models, and refresh scheduling, plus a few smaller token/math reuse
opportunities. Similar-looking security, scheduling, presentation, and widget
state paths remain specialized where their contracts differ.

## Ranked Findings

### 1. World session path construction is duplicated exactly

**Classification:** APPLY — HIGH VALUE / LOW RISK
**Owners:** `runtime/world_state.py::_world_session_store_path` and
`runtime/world_materialize.py::_world_session_store_path`

Both functions perform the same slot validation, SHA-256 world-ID digest, and
`world-sessions/{digest}/{slot}.json` construction with identical diagnostics.
The persistence mixin calls the copy in `world_state.py`; the copy in
`world_materialize.py` has no in-repository callers. It is nevertheless listed
in that module's `__all__`, so compatibility should be checked before removing
or redirecting that name.

**Recommendation:** Make `world_state.py` the single implementation owner and,
if the exported private name must remain supported, re-export/delegate to it
from `world_materialize.py`. Keep slot validation and output path behavior
unchanged. Relevant coverage: `tests/test_world_state.py` exercises save/load
paths and persistence.

### 2. Behaviour-script resource policy repeats in two editor operations

**Classification:** APPLY — HIGH VALUE / LOW RISK
**Owner:** `editor/script_tools.py`

`create_behaviour_script` and `attach_script` both enforce the
`project://scripts/*.py` policy: project scheme, `scripts/` path prefix, and
`.py` suffix. The class-name predicate is already shared through
`_valid_behaviour_class_name`, but the resource-path predicate is duplicated.

**Recommendation:** Consider a small private predicate accepting a `ResourceId`
and reuse it at both call sites. Keep path creation's root-confinement check and
attach's duplicate-component check in their current owners; those are separate
contracts. Existing tests: `tests/test_script_tools.py`.

### 3. Entity behaviour eligibility is repeated across dispatch methods

**Classification:** APPLY — HIGH VALUE / LOW RISK
**Owner:** `core/entity.py`

`Entity.on_update`, `on_frame_update`, and `on_action_event` repeat the same
eligibility policy: the Entity is enabled, the Behaviour is still owned by that
Entity, the Behaviour is enabled, and it is not system-owned. Their callback
signature compatibility and event-specific dispatch behavior are different.

**Recommendation:** If changed, centralize only enumeration/filtering of
eligible behaviours in a private Entity helper. Leave update-signature
fallbacks, frame-update behavior, and input-consumption semantics in the three
specialized methods. Existing coverage is primarily in
`tests/test_behaviour_system.py` and `tests/test_runtime_behaviour.py`.

### 4. Project scene/document resolution duplicates the root-containment guard

**Classification:** APPLY — HIGH VALUE / MODERATE RISK
**Owner:** `core/project.py`

`Project.scene_file` and `Project.document_file` both resolve the candidate path
and call `relative_to(self.path)` to reject paths escaping the project, including
symlink escapes. Their earlier validation, default selection, and user-facing
error messages differ and should remain specialized.

**Recommendation:** Consider one Project-owned containment helper for the
resolve-and-check invariant, with each caller mapping escape failures to its
existing error wording. Preserve validation order and add focused tests for
both document path methods, especially symlink escapes. Project path and load
coverage is in `tests/test_project.py`; related project-script symlink coverage
is in `tests/test_project_workflow.py`.

### 5. Recursive clone and Scene Instance materialization duplicate remapping

**Classification:** APPLY — MEDIUM VALUE / MODERATE RISK
**Owners:** `core/scene/scene.py::Scene.clone_entity` and
`core/scene/scene_instance.py::_materialize_source_scene`

Both implementations create fresh entity IDs, remap parent IDs, copy entity
state/components/tags, and add cloned entities to a Scene. They already share
`_clone_components_and_tags`. The root-parent rules differ: ordinary cloning
keeps a cloned root under its existing parent, while Scene Instance roots attach
under the instance entity. The latter function explicitly documents that it
mirrors `clone_entity` with this difference.

**Recommendation:** Consider sharing only the low-level ID-remapping and entity
construction mechanism, with the root-parent policy explicit at the call site.
Do not merge the public clone and materialization operations. Existing coverage:
`tests/test_scene_lifecycle.py`, `tests/test_scene_instance.py`, and
`tests/test_scene_world_transform.py`.

### 6. Runtime scalar and vector coercion helpers are repeated

**Classification:** APPLY — MEDIUM VALUE / MODERATE RISK
**Candidate owners:** `runtime/visual_components.py`,
`runtime/animated_sprite_2d.py`, `runtime/area.py`, `runtime/audio_2d.py`,
`runtime/screen_texture.py`, `runtime/lighting_2d.py`, `runtime/collider.py`,
and `runtime/rendering.py`

Several modules maintain near-identical `_finite` conversion helpers; vector
helpers also recur in visual components, animated sprites, and areas. Some
versions accept arbitrary objects and translate conversion failures; others
accept typed floats or expose different messages. Domain constraints (positive,
non-negative, bounded, exact length) remain local.

**Recommendation:** If this is implemented, first choose the exact compatible
conversion contract and consolidate only matching scalar/vector mechanics.
Keep domain validation, field labels, and public exception wording specialized.
Avoid a generic validator with mode flags. Relevant existing tests include
`tests/test_area.py`, `tests/test_render_extractor.py`,
`tests/test_lighting_2d.py`, `tests/test_screen_texture.py`, and
`tests/test_audio_2d.py`.

### 7. Editor path-to-project-relative conversion is repeated

**Classification:** APPLY — MEDIUM VALUE / MODERATE RISK
**Candidate owners:** `editor/project_workflow.py`,
`editor/world_authoring.py`, and `editor/interactions.py`

Several editor workflows convert a selected or active document path to a
project-relative path using `resolve()`/`relative_to()`. Failure behavior
differs: some show a dialog, some return `None`, and the current-scene helper in
`interactions.py` uses `relative_to()` without resolving first. The in-progress
worktree also has path conversion in asset selection and save flows.

**Recommendation:** Before consolidation, decide whether the common operation
is strict or optional and whether it resolves symlinks. A low-level conversion
helper may be useful, but callers should retain their own UI/error policy and
the implementation must not silently change the current-scene comparison's
normalization semantics. Related code: `ProjectWorkflow._current_relative_path`,
`open_document`, `WorldAuthoringWorkflow._active_world_path`, and
`interactions._current_scene_relative_path`. The implementation follow-up uses
separate resolved and lexical helpers to keep these semantics explicit.

### 8. Export verification parses two manifests with duplicated error mapping

**Classification:** KEEP — CURRENT FORM CLEARER (LOW-PRIORITY EXTRACTION)
**Owner:** `export/verify.py`

`verify_export` separately reads/parses `build_manifest.json` and
`asset_manifest.json`, with matching `JSONDecodeError`/`OSError` handling but
different filename-specific diagnostics and different validation that follows.
The duplicate is small and within one verifier.

**Recommendation:** Keep unless manifest parsing grows or its failure behavior
needs a single policy. If extracted, preserve the distinct filenames and error
text; do not combine the subsequent schema validation. Existing verification
coverage is in `tests/test_export_verify.py`.

## Supplemental Audit: Remaining Engine Packages

The remaining `coordinators/`, `design/`, `messages/`, `schema/`, `ui_model/`,
`ui/`, and root-level modules were inspected after the first implementation
pass.

### 9. Finite-float and clamp helpers cross the core, runtime, coordinator, and UI-model boundary

**Classification:** APPLY — MEDIUM VALUE / MODERATE RISK
**Candidate owner:** `core/math_utils.py`

The first implementation added `runtime.validation.finite_float` and reused it
within runtime modules. The wider scan found equivalent typed-float validation
in `ui_model.controls._finite` and `coordinators.refresh_scheduler._finite_time`.
The error labels are caller-specific but fit the `finite_float(value, name)`
contract. `ui_model` should not import a runtime-owned utility; `core/math_utils`
is the lower-level numeric owner already used by runtime models. Also,
`ui_model.controls._clamp` duplicates `core.math_utils.clamp`; its callers
validate ranges first, and the core helper allows equal bounds as the controls
model does.

**Recommendation:** Consider moving the common typed `finite_float` helper to
`core/math_utils.py`, preserving the current runtime import as a compatibility
re-export if desired, then use it from controls and refresh scheduling. Replace
`controls._clamp` with the core clamp only after verifying its error ordering
remains unreachable for valid constructors. Keep `coerce_finite_float` and
`pair_values` in `runtime.validation`: they handle runtime-specific object
coercion and vector diagnostics.

Relevant tests: `tests/test_core_math_utils.py`,
`tests/test_ui_model_controls.py`, and `tests/test_refresh_scheduler.py`.

### 10. UI style typography and default accent values partially duplicate design tokens

**Classification:** APPLY — LOW VALUE / LOW RISK
**Owners:** `design/tokens.py` and `ui/styles.py`

`ui/styles.py` already consumes canonical semantic colors and spacing. Its
backend font tuples repeat the size/weight values for body, section, title, and
mono roles that are present in `TYPOGRAPHY_SCALE`; font families and Tk-specific
style aliases remain presentation-adapter details. The `cyan` entry in
`ACCENT_THEMES` also repeats the default semantic accent and active-accent
values.

**Recommendation:** Consider deriving the shared font-size/weight portions and
the default cyan accent values from `design.tokens`, while leaving font
families, Tk style aliases, and non-token control metrics in `ui.styles.py`.
Existing coverage is in `tests/test_design_tokens.py` and the UI style tests.

## Remaining Packages: KEEP / Existing Owners

- **Coordinator lifecycles:** `AppCoordinator` owns background task execution,
  cancellation, per-key reruns, and delivery. `UICoordinator` owns render
  batching, target generations, visibility, and presentation commits. Similar
  pending/generation concepts do not have the same state machine contract.
- **Delayed transitions:** `PendingTransition` is already the shared timer
  owner used by `UICoordinator`; no additional transition mechanism was found.
- **Tree reconciliation:** `ui/tree_reconciliation.py::reconcile_treeview` is
  reused by both hierarchy and asset-browser trees. This is a good existing
  consolidation boundary.
- **Control-model variants:** `ui_model.slider.SliderModel` and
  `ui_model.controls.Slider` have different semantics: one exposes a normalized
  fraction and permits step zero; the other supports live/committed values and
  permits equal bounds. They are separately exported/tested and should not be
  merged without a product-level canonical contract.
- **Observability duration checks:** `finish` and `record` repeat the same small
  finite/non-negative duration guard. They validate at different lifecycle
  points (token validation under lock versus record argument validation before
  locking); the current duplication is small and moving it risks obscuring that
  ordering for little benefit.
- **Messages and generated schemas:** message modules delegate bounded text and
  representation to `messages/_format.py` while retaining domain-specific
  wording. Protobuf bindings under `schema/generated/` are generated from
  `schemas/*.proto`; they remain generated output and are not manual
  consolidation targets.
- **UI overlays and panels:** viewport markers, World overlays, lighting gizmos,
  and camera overlays each render different domain objects and interaction
  states. `ui/styles.py` also imports the semantic color and spacing owners
  already; no larger widget/style owner is indicated by the current code.

## Keep Separate / Existing Owners

- **`runtime/ui/`:** `LayoutSpec` delegates rectangle layout to
  `ui_model.geometry`; Button state delegates to `ui_model.controls`. The
  runtime package owns tree traversal, hit testing, focus, and event dispatch.
  `Viewport` permits zero dimensions while pixel-perfect scale targets require
  positive dimensions, so these dimension checks are not interchangeable.
- **Filesystem confinement:** `DirectoryMount`, archive extraction, and
  `UserDataStore` each resolve paths under different security and lifecycle
  rules. Directory writes re-resolve after creating parents; user-data access
  explicitly rejects symlink components; archive extraction also protects
  cache targets. Do not replace these with one generic path check without
  proving the threat model and race guarantees remain intact.
- **Resource IDs vs. user-data paths:** `ResourceId` validation and
  `UserDataStore` path validation overlap on traversal rejection but carry
  different logical-ID, namespace, and safe-diagnostic contracts.
- **Atomic persistence:** `core/persistence.py` is already the canonical
  atomic-write implementation used by user-data and editor persistence. Asset
  import uses a no-overwrite hard-link promotion; archive extraction uses a
  content-addressed cache; project creation stages a directory. These are
  intentionally different replacement policies.
- **Document/component registry boundaries:** Scene/Level/World codecs retain
  distinct document meanings while sharing their codec path. Component
  serialization and editor property specifications remain separate registries
  with registration helpers keeping them in sync.
- **World editor vs. runtime travel validation:** the editor validates authored
  endpoint types and static seamless adjacency; runtime transition code checks
  active levels, current anchors, and live transition state. Their similar
  connection checks serve different lifecycle states.
- **Export target packagers:** Linux and Windows runtime/package installation
  have different filesystem layouts and pip options. Keep target-specific
  mechanics specialized behind the existing `TargetPackager` contract.
- **Exporter failure boundaries:** pipeline, verification, and promotion each
  map errors to export failure events, but they bracket distinct transactional
  stages. No shared wrapper is recommended unless it preserves stage-specific
  progress and cleanup behavior.

## Current Ownership Decisions

| Responsibility | Current owner | Decision |
|---|---|---|
| Unknown component type wording | `messages/component.py` | Consolidated in commit `4723b25`; both deserialization and schema lookup use it while retaining their exception types. |
| World-session storage path | `world_state.py::_world_session_store_path` | Implemented once; `world_materialize.py` preserves its alias/export. |
| Behaviour-script resource location | `script_tools.py::_is_behaviour_script_resource` | One predicate used by creation and attachment. |
| Entity behaviour eligibility | `Entity._eligible_behaviours` | Shared lazy iterator; eligibility remains live during event dispatch. |
| Project-root document confinement | `Project._resolve_project_path` | Shared resolved containment check; caller errors remain distinct. |
| Entity ID/parent remapping | `core/scene/scene.py::_clone_entity_tree` | Shared by recursive clone and Scene Instance materialization; root policy remains explicit. |
| Runtime numeric conversions | `runtime/validation.py` | Shared only across compatible runtime callers; lower-level owner review remains a supplemental finding. |
| Editor project-relative conversion | `editor/project_paths.py` | Separate lexical/resolved APIs preserve call-site normalization. |
| Filesystem and document-specific validation | Existing specialized owners | Keep separate where input contracts or security policies differ. |

## Implementation Follow-up

The APPLY findings were implemented against the current tree after
`da26d1d`. Specialized caller behavior was retained:

1. `world_materialize._world_session_store_path` now re-exports the canonical
   helper from `world_state`, retaining the existing `__all__` name.
2. Script creation and attachment use one project-script resource predicate.
3. Entity event methods share a lazy eligibility iterator; it snapshots the
   attached-behaviour list but evaluates eligibility as iteration proceeds, so
   a callback that removes a later behaviour still prevents that behaviour from
   running in the same dispatch.
4. `Project.scene_file` and `Project.document_file` share the resolved
   project-root containment check and retain their distinct `ProjectError`
   messages.
5. Recursive cloning and Scene Instance materialization share ID/parent
   remapping and entity construction, with root-parent policy passed explicitly.
6. Runtime `finite_float`, object-to-finite conversion, and pair-shape parsing
   are shared for compatible callers. Area retains its “exactly two” vector
   wording; lighting keeps its distinct conversion/non-finite diagnostics and
   was not migrated to the shared scalar helper.
7. Editor workflows use `resolved_project_relative_path` for normalized path
   conversion; the current-scene comparison uses `project_relative_path` to
   retain its previous lexical, non-resolving behavior.

Finding 8 and the KEEP-SEPARATE decisions were left unchanged.

Supplemental findings 9–10 are documented opportunities from the wider audit;
they were not included in the initial implementation set.

### Verification

Audit-time inspection itself was static; the following tests were run during
the implementation follow-up:

| Command scope | Result |
|---|---|
| `tests/test_world_state.py` | 10 passed |
| `tests/test_script_tools.py` | 7 passed, 6 subtests passed |
| `tests/test_entity.py tests/test_runtime_behaviour.py tests/test_behaviour_system.py` | 56 passed |
| `tests/test_project.py tests/test_project_world.py` | 41 passed |
| `tests/test_scene_lifecycle.py tests/test_scene_instance.py tests/test_scene_world_transform.py tests/test_composition_workflow.py` | 46 passed |
| Runtime validation, Area, rendering, audio, animation, screen-texture, and lighting tests | 117 passed, 15 subtests passed |
| Editor project paths, project workflow, World authoring, composition, multi-level workflow, and script-tools tests | 77 passed, 6 subtests passed |
| `tests/test_world_state.py tests/test_world_streaming.py` | 48 passed |
| Consolidated regression run over all affected core/runtime/editor tests | 375 passed, 21 subtests passed |

After the final resolved-vs-lexical editor path helper split, the Tk-heavy tests
were rerun separately: `tests/test_multi_level_workflow.py` passed 12 tests, and
the editor-path/project-workflow/World-authoring/composition/script-tools group
passed 65 tests plus 6 subtests. A later monolithic rerun aborted during Tk asset
worker teardown without a pytest assertion failure; the isolated reruns passed.

Focused Ruff import/unused-import checks were also run. Whole-file Ruff checks on
some touched runtime modules report existing unrelated rules in those modules
(late registration imports, default `Color(...)` calls, enum style, and quoted
annotations); no changes were made for those unrelated diagnostics. Focused
Pyright on the new runtime-validation and editor-project-path modules reported
0 errors. The repository-wide `pyright` profile exited 1 with 721 diagnostics,
including existing World/project typing issues and editor mixin-attribute errors.

## Audit-Time Worktree

At the original audit, no implementation files were edited and no tests were
run. The worktree was dirty; unrelated changes and the untracked `To` file were
preserved. The implementation follow-up changed only the findings described
above, their focused tests, and this report; it did not modify `To`. The
untracked `docs/specs/2026-09-28-normal-mapping-design-revised.md` was also
present during implementation and was preserved untouched.
