# Bug findings — volume 1

## BUG-20260929-001 — Editor permits edits to non-persisted Scene Instance children

- **Status:** Candidate — four opposition reviews complete; Full B7 incomplete because Agent 5 was declined by the user
- **Severity:** P2 (user-authored edits can be silently discarded)
- **Confidence:** High; reproduced in a temporary project using actual Qt input and Save
- **First observed:** 2026-09-29
- **Fix status:** Not fixed; this audit made no production-code or test-tree changes
- **Evidence:** [`BUG-20260929-001 opposition`](../opposition/BUG-20260929-001-opposition.md)
- **PoC:** [`Qt edit/delete reproduction`](../poc/BUG-20260929-001/scene_instance_editor_poc.py)
- **Fix plan:** [`BUG-20260929-001 fix plan`](../plans/BUG-20260929-001-fix-plan.md)

### Contract and impact

The editor exposes edit/delete operations for entities shown in the hierarchy. An
accepted edit should either be represented by the active authored document and
survive Save/reopen, or be rejected with an explanation and an actionable route
to the owning source. Scene Instance descendants are materialized from their
source and omitted by canonical serialization, but the editor's ordinary entity
mutation handlers do not route or reject those edits. Position edits, deletion,
and exposed script-value edits therefore appear to work, Save marks the active
document clean, and reopening regenerates the original child state.

### Evidence

- `Scene.to_dict(include_instance_content=False)` filters materialized entity IDs;
  `Project.save_document()` uses that serialization before writing a Scene/Level.
- `Project.read_document()` resolves Scene Instances after construction, recreating
  the filtered descendants on reopen.
- `EditorWindowCore` entity handlers and `editor/interactions.py` commands accept
  those same materialized IDs without an authorability check.
- The hierarchy labels generated rows `[in]`, but the selection/action path still
  enables edit/delete and the inspector remains active.
- Temporary Qt reproduction: an actual QLineEdit edit changed `x` from `1.0` to
  `9.5`; after toolbar Save and reload it returned to `1.0`. Deleting the generated
  child also caused it to reappear.
- Temporary Qt reproduction with a script override: editing the generated
  `open_speed` value from `9.0` to `11.0` and saving/reopening restored `9.0`; the
  owning SceneInstanceComponent override remained unchanged.
- Existing tests cover source serialization omission and direct override
  resolution, but do not assert that editor mutations of materialized descendants
  are blocked or routed to their authored owner.

### Affected editor operations

Position/rotation/scale, viewport drag, rename, enabled toggle, delete, component
add/remove/change, and script exposed-value edits all operate on the materialized
entity. Unless an operation is explicitly translated into an authored instance
override, the owner document serializer omits that mutation.

### Related boundary

Reparenting an ordinary authored entity beneath a materialized child can leave
the authored entity referring to a parent omitted by serialization. The document
codec rejects the resulting missing-parent reference, so Save fails instead of
writing an invalid hierarchy. This is a related authoring-boundary case; UI error
presentation still needs separate verification.

### Review status

Four opposition reports converge on the editor guard/feedback mismatch. Agent 5
was not run at the user's explicit direction, so this remains a candidate rather
than a BugGuard-validated bug. See the opposition report for reviewer findings
and the linked plan for the proposed implementation sequence.
