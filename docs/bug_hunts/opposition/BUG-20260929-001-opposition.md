# Opposition Review — BUG-20260929-001

**Candidate bug:** BUG-20260929-001
**Created:** 2026-09-29
**Current cycle:** 1 / 3
**Candidate entry source:** `docs/bug_hunts/bugs_found/bugs_found_1.md#bug-20260929-001--editor-permits-edits-to-non-persisted-scene-instance-children`
**Threshold:** Full B7 — editor/persistence cross-boundary behavior
**Fix plan:** [`BUG-20260929-001 fix plan`](../plans/BUG-20260929-001-fix-plan.md)

## Artifact ownership

The main auditor owns this scaffold, candidate summary, evidence index, and final
synthesis. Each reviewer owns and must directly write only their assigned section.

## Original candidate summary

Scene Instance descendants are resolved from a source Scene, shown as ordinary
hierarchy entities with an `[in]` marker, and accepted by the editor's normal
mutation handlers. `Scene.to_dict(include_instance_content=False)` omits those
materialized descendants, and Project save uses that compact form. Reopening
resolves the original source content again. Actual Qt reproductions show position,
delete, and script exposed-value edits do not survive a Save/reopen cycle.

The data model's non-serialization of generated descendants appears intentional
and documented. The candidate is specifically the editor's allowing/appearing to
commit edits that have no authored destination, rather than the serialization
policy itself.

## Candidate evidence index

- `src/expra_engine/core/scene/scene.py` — materialization bookkeeping and
  serialization filter.
- `src/expra_engine/core/scene/scene_instance.py` — source resolution and limited
  exposed-script-value override contract.
- `src/expra_engine/editor/window_core.py` — ordinary entity mutation handlers.
- `src/expra_engine/editor/interactions.py` — component, multi-delete, duplicate,
  and reparent command paths.
- `src/expra_engine/editor/qt/inspector.py` — edit controls remain available for
  materialized entities.
- `src/expra_engine/editor/hierarchy_rows.py` — `[in]` marker projection.
- `src/expra_engine/core/project.py` — canonical typed document save/load.
- `docs/guide/SCENE_INSTANCES.md` — documented source/materialization semantics.
- `tests/test_scene_instance.py`, `tests/test_multi_level_workflow.py`,
  `tests/test_blacksite_level2_dogfood.py` — current related coverage.
- `docs/bug_hunts/poc/BUG-20260929-001/scene_instance_editor_poc.py` — reproducible
  temporary-project Qt interaction PoC.
- Additional temporary Qt script-field reproduction: edited exposed `open_speed`
  from 9.0 to 11.0; after Save/reopen it returned to 9.0 and the owning instance
  override stayed 9.0.
- Additional temporary reparent reproduction: moving an authored entity under a
  generated child makes `Project.save_document()` reject the missing parent ID
  after the generated child is omitted. Whether the Qt Save action surfaces that
  exception clearly remains unverified.

## Test evidence synthesis

| Evidence | Path/command | What it tested | Result | Supports bug | Disproves bug | Gaps |
|---|---|---|---|---|---|---|
| Main PoC | `PYTHONPATH=. ./.venv/bin/python docs/bug_hunts/poc/BUG-20260929-001/scene_instance_editor_poc.py` | Real Qt position edit and delete, then Save/reopen in disposable projects | Passed: x changed 1.0→9.5 then reloaded as 1.0; deleted child absent before Save and present after reopen | Yes | No | Temporary synthetic projects; not user's project |
| Existing Scene Instance tests | `tests/test_scene_instance.py` | Resolver, override and compact serialization contracts | 19 passed | Shows persistence policy | No | Does not test editor mutation safety |
| Existing workflow tests | `tests/test_multi_level_workflow.py` | Canonical save and instance-content omission | 12 passed | Shows save excludes generated children | No | Does not test actual edit attempt |
| Blacksite dogfood | `tests/test_blacksite_level2_dogfood.py` | Source edits and per-instance overrides | 2 passed | Shows direct source/override model | No | Does not exercise editor overrides |
| Editor document roundtrip | `tests/test_editor_document_roundtrip.py` | Ordinary authored Scene/Level/World editor save | 6 passed | Narrows behavior to generated state | No | Does not include a Scene Instance |

## Cycle 1 — Opposer 1: Reproduction Skeptic

### Independent reproduction

Environment was the checked-out Expra source at `b03ff951fc11bc1864a6efd25e11c00b19e1ac07`,
dirty working tree, Python 3.12.3, Expra 0.6.1.0 imported from `src/expra_engine`,
PySide6 6.11.2, with display `:0`. I ran the supplied command unchanged:

```text
PYTHONPATH=. ./.venv/bin/python docs/bug_hunts/poc/BUG-20260929-001/scene_instance_editor_poc.py
```

It completed successfully and printed:

```text
{'position_in_editor_after_real_qt_input': 9.5, 'position_after_save_and_reopen': 1.0, 'child_present_after_editor_delete': False, 'child_present_after_save_and_reopen': True}
```

This independently reproduces both reported outcomes using actual Qt input/save,
with disposable projects created by the script. I found no reproduction flaw
that overturns those results.

### Counterexample: authored Scene Instance root

I added and ran a separate, PoC-local counter-test (no production source or main
tests were edited):

```text
PYTHONPATH=. ./.venv/bin/python docs/bug_hunts/poc/BUG-20260929-001/authored_root_counterexample.py
```

It creates a source Scene with a generated child and an owner Scene whose
authored `Authored Instance Root` has both a Transform and SceneInstance
component. It selects that root in the Qt editor, changes x from 2.0 to 9.5 via
the inspector's real Qt key events, saves, closes, then reloads through
`Project.load(...).load_document(...)`. Result:

```text
{'root_x_after_qt_edit': 9.5, 'root_x_after_save_reopen': 9.5, 'materialized_children_after_reopen': ['Generated Child']}
```

Thus, editing the authored instance root is a concrete counterexample to a
broader claim that edits anywhere on/under a Scene Instance fail persistence.
The root edit persists and the generated child still resolves after reopen.
The authored-root counterexample narrows the candidate to **materialized
descendants**, consistent with its stated scope; it does not disprove the scoped
bug.

### Source/test cross-check and bounds

In `src/expra_engine/core/scene/scene.py`, `to_dict(include_instance_content=False)`
filters IDs collected from `_instance_children` (lines 345–363); the bookkeeping
comment (102–105) identifies these as materialized descendants and describes
them as runtime-only. The authored root is not in that descendant-ID set, which
explains why its Transform survives. The supplied PoC tests a child Transform
edit and deletion, not the authored root, and its observed results agree with
that serialization boundary.

`tests/test_editor_document_roundtrip.py` exercises repeated save/reopen for
ordinary authored Scene/Level entities and World placement, but does not include
a Scene Instance. This review did not rerun the complete test suite; the focused
Qt reproduction and independent Qt counter-test above are the behavioral
evidence. I did not attempt to classify the intended product contract for
editing generated content: the evidence establishes that accepted child edits
are lost under the current save path, while authored root edits persist.

**Opposer 1 conclusion:** candidate survives, narrowed/confirmed as an editor
mutation/persistence mismatch for materialized Scene Instance descendants. The
root counterexample rules out extending the claim to authored instance roots or
ordinary authored entities.

## Cycle 1 — Opposer 2: Repo-Truth Skeptic

**Independent verdict: narrow; retain as a missing editor guard/feedback finding, not a serialization defect.**

Repo truth supports intentional source re-resolution: `docs/guide/SCENE_INSTANCES.md`
§How it works says descendants are tracked, never serialized, and regenerated on
load; §Overrides specifies the supported per-instance edit surface narrowly as
`ScriptComponent.exposed_values`. `docs/guide/DOCUMENT_MODEL.md` §Save/reopen
repeats that Scene documents omit materializations and resolve them on reopen.
`Scene.to_dict(include_instance_content=False)` documents the same deliberate
filter (`src/expra_engine/core/scene/scene.py:345-363`). Thus edits to ordinary
materialized transform/name/enabled/components are not persistence promises and
must not be framed as broken save semantics. The supported instance customization
is the root transform plus the root component's named exposed-value overrides
(`scene_instance.py:62-71`; guide §Overrides).

There is nevertheless concrete editor-contract evidence against calling all
mutation acceptance intended. `hierarchy_rows.py:61-64` marks descendants `[in]`,
but that is identification, not a stated read-only affordance; `scene.py:102-105`
only says bookkeeping lets the editor mark content “read-only-ish.” The ordinary
editor handlers still push rename, delete, transform, enable, exposed-value, and
component commands for any found entity (`window_core.py:347-429`; component
paths in `interactions.py:30-63`). The hierarchy marker and inspector/edit
controls therefore permit a normal-looking edit with no authored destination.
The guide documents regeneration but does not instruct users that editing these
rows is transient or disabled. Existing round-trip evidence in the candidate
index shows edits can appear accepted and then revert; this is a misleading
feedback/guard gap even though the persistence policy itself is correct.

Nuance: exposed script values are only persistent instance overrides when
authored on the `SceneInstanceComponent.overrides` map. Editing the materialized
script field alone does not establish that override. Dogfood
`tests/test_blacksite_level2_dogfood.py` proves source-scene edits propagate and
an explicitly configured instance override stays local (lines 272-342); it does
not assert that editing a materialized descendant through the editor persists.
`tests/test_scene_instance.py` tests override and serialization mechanics, not
editor editability. `tests/test_project.py:505-518` likewise confirms compact
save, without editor mutation coverage. These tests establish intended model
semantics, not intended UX for accepting transient edits.

Accordingly, reject the broad claim “instance descendants should serialize” and
narrow BUG-20260929-001 to: **the editor allows mutations to `[in]` generated
descendants without an explicit transient-edit warning or guard, so users can
mistake runtime/materialized changes for authored changes; reparenting authored
entities under omitted descendants may additionally make the saved hierarchy
invalid.** A guard should distinguish supported instance-root transforms and
explicit overrides from generated-descendant fields, or clearly disclose their
transient status. I ran no commands and added no counter-test in this review;
the commands/results summarized in the shared evidence index are the main
auditor's evidence, not independent executions by this opposer.

## Cycle 1 — Opposer 3: Architecture/Security Skeptic

### Independent assessment

**Verdict: confirm a real editor-contract/persistence bug, with medium severity and
bounded scope.** The candidate is not a serializer defect: generated descendants
are explicitly resolve-from-source state, and compact persistence is correct for
that ownership model. The defect is that the editor presents and mutates those
descendants through the same writable hierarchy/inspector paths as authored
entities, without redirecting supported instance-level edits to an authored
override or refusing the operation. Users receive normal undo/dirty/save feedback
for changes that have no serialized owner.

### Ownership and reachability

- `SceneInstanceComponent` on the authored instance root is the persistent owner.
  Its `source_path`, root `TransformComponent`, and `overrides` are serialized.
  The resolver deep-copies source entities, applies override values, and records
  their IDs in runtime-only `Scene._instance_children` bookkeeping.
- `Scene.to_dict(include_instance_content=False)` filters only those tracked IDs;
  `Project.save_document()` uses this form for Scene documents. `Level` forwards
  the option to `Scene`, so the same boundary applies to Levels. The generic
  serializer's default remains full content; runtime snapshots/other callers are
  not the compact authored save path.
- Scene and Level hierarchy rows remain selectable and inspector controls remain
  active for materialized IDs. Generic transform, component-property, script
  exposed-value, enabled, rename, add/remove-component, delete, duplicate, and
  reparent commands address the selected entity ID directly. The reported
  transform/delete/script cases are therefore reachable in the live editor. The
  exact persistence outcomes differ: descendant field edits and deletion are
  omitted then regenerated; script edits change only the cloned component, not
  the owning root's `SceneInstanceComponent.overrides`; duplicate clones are
  normal new entities (but may carry a parent that was omitted); reparent can
  move an authored child under a generated parent and produce a dangling
  `parent_id` in the compact document.
- The override schema is intentionally limited to
  `entity name -> exposed-value key/value`, with first matching name selected.
  Root transform is the documented instance transform override. There is no
  documented child transform/delete/structural override contract. Thus these
  operations should either be clearly blocked/read-only or deliberately have
  separately designed authored semantics; blindly serializing materialized
  descendants would violate instancing/source identity.

### Undo, dirtiness, autosave, and isolation

The generic commands do correctly mutate the edit scene and support undo/redo.
They do not alter the instance root's authored override data for a generated
script field. Each pushed edit participates in `CommandStack` dirtiness; explicit
Save and recurring silent autosave both call the canonical document save, then
`mark_saved`/`mark_clean`. This can mark the document clean despite the generated
change being absent from disk, making dirty-state feedback a secondary contract
failure rather than a persistence mechanism. Undo before save restores the
in-memory generated entity as expected; it cannot make a non-owned edit persist.

The edit/play boundary is not implicated: mutation handlers gate on EDIT, and
Play operates on runtime state that Stop restores from the edit scene. World is
also not implicated in this candidate: it has no editable Entity Scene graph and
its descriptors/relationships use separate World authoring commands and
serialization. Reparenting and persistence concerns apply to Scene and Level
entity documents, not World documents.

### Impact, severity, and fix regression risks

Impact is authoring data loss/confusion for projects that select generated
descendants and edit them; the defect does not corrupt source scenes merely by
editing a materialized clone. Reparenting an authored entity under a generated
descendant is the more serious edge: compact save can contain an entity whose
parent ID is omitted, and typed document validation can reject reload/save. This
failure is conditional on that structural combination; the Qt error presentation
is not established by current evidence. Severity should therefore remain
**medium**, not elevated to broad project corruption or runtime safety impact.

Fix risks to retain in the primary synthesis:

1. Do not serialize resolver-generated descendants as a shortcut; that breaks
   canonical source identity, risks duplicate/stale content on re-resolution,
   and changes the explicit compact-save contract.
2. Any read-only policy must cover every mutation ingress, not just disabled
   inspector widgets: single/multi-delete, viewport transforms, drag reparent,
   duplicate, add/remove component, script edit, rename, and command/undo paths.
   Selection and copy/navigation may remain useful.
3. Guarding reparent must account for both directions: an authored entity moved
   under generated content creates a dangling-parent serialization hazard, while
   moving a generated child outside its instance undermines ownership and may
   still be filtered. Preserve ordinary authored-to-authored reparent and valid
   whole-instance operations.
4. If script exposed-value editing is meant to be supported per instance, write
   the value to the root override map using the existing name/key contract, then
   keep the materialized view, undo/redo, validation, duplicate-name behavior,
   and save/load resolution coherent. Do not accidentally turn generated
   component edits into source-scene edits.
5. Save/autosave clean-state handling should reflect whether a mutation had a
   persistent destination; otherwise rejected/no-op commands can still create
   misleading undo and dirty transitions.

Evidence basis: current source at workspace SHA `b03ff951fc11bc1864a6efd25e11c00b19e1ac07`
(dirty tree), especially `core/scene.py`, `core/scene_instance.py`,
`core/project.py`, `editor/interactions.py`, `editor/commands.py`,
`editor/window_core.py`, `editor/active_document.py`,
`editor/project_workflow.py`, and `docs/guide/SCENE_INSTANCES.md`. No production
code or tests changed and no new counter-test was run in this opposer cycle.

## Cycle 1 — Opposer 4: External-Research Skeptic

**Independent review — external-research necessity and contract check**

External library/framework research is unnecessary for this claim: the decisive
behavior is specified and implemented inside Expra before any external serializer
or UI framework could affect the result. `Scene.to_dict(include_instance_content=False)`
filters IDs recorded as materialized instance descendants; `Project.save_document()`
passes that filtered dictionary to protobuf encoding for Scene documents
(`src/expra_engine/core/scene/scene.py`, `src/expra_engine/core/project.py`). The
legacy `save_scene()` path uses the same filter. Therefore Protobuf serialization
cannot restore omitted descendants. Qt signal or save timing would matter only if
the edits were not applied to the in-memory objects before serialization; the
reported editor reproductions and the editor mutation paths concern actual object
mutations, while the save filter is evaluated on the current scene at serialization
time. No concrete unresolved Qt or Protobuf semantic question was found that would
justify consulting external documentation.

Potential contract counterexample checked: this is not a claim that instance
descendants must always be persisted, or that all prefab systems behave alike.
Expra's own `Scene` comments describe the bookkeeping as runtime-only, the
serializer documents omission as intentional, and the candidate summary notes the
documented resolve-from-source model. That contract supports omission itself. It
does not establish that ordinary editor mutations to those entities are disabled,
redirected to the source scene, or converted into supported per-instance overrides;
the indexed normal editor mutation handlers and reported Save/reopen reproductions
are evidence against those alternatives. Thus external conventions do not
invalidate the narrower UX/persistence claim.

**Verdict: candidate survives this opposition.** No external-research-based
counterexample found; the source contract explains why data disappears, while the
independent question remains whether the editor should accept and present such
edits as ordinary mutations. This review did not run a new interaction test.

## Agent 5 — Superpower Evidence Auditor

**Not run — explicitly declined by the user.** The four opposition sections are
available, but the required Agent 5 evidence audit was intentionally omitted.
This remains an incomplete Full B7 review and is not labeled a BugGuard-validated
bug. The implementation proposal is recorded in the linked fix plan.

## Main auditor synthesis and rebuttal

The four reviewers agree that compact serialization and source re-resolution are
intentional. The surviving finding is narrower: generated descendants remain
selectable and writable through ordinary editor paths, although their mutations
have no persisted owner; exposed script values also mutate the clone rather than
the instance root's override map. Opposer 1 reproduced position/delete behavior
and verified that authored instance-root transform changes persist. Opposer 3
identified the missing-parent save-validation edge when authored content is
reparented under generated content. Opposer 2 recommends framing this as a missing
editor guard/feedback issue, not a serializer defect; Opposer 4 found no external
semantics that overturn Expra's evidence.

**Decision for planning:** retain the editor authoring-boundary candidate at
medium severity and use the linked consolidation-led plan. Do not serialize
materialized descendants as a shortcut. Because Agent 5 was not run at the user's
direction, Full B7 remains incomplete and no final BugGuard validation is claimed.
