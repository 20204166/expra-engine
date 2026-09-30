"""Single admission decision for editor mutations against linked vs authored entities.

Scene Instance descendants are materialized from a source Scene and omitted from
compact saves; they are regenerated on load. Every editor mutation must therefore
either target an authored entity (whose change persists), route to an authored
instance override, or be rejected before it can create misleading undo/dirty state.

This module is the single owner of that admission decision. It decides; it does
not absorb the operation-specific command behavior that remains in
``editor/commands.py`` and the individual editor handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from expra_engine.core.scene import SceneInstanceComponent
from expra_engine.core.scene.scene import Scene


class MutationVerdict(Enum):
    """The admission outcome for one editor mutation request."""

    ALLOW_AUTHORED = "allow_authored"
    ROUTE_INSTANCE_OVERRIDE = "route_instance_override"
    REJECT_LINKED = "reject_linked"


@dataclass(frozen=True, slots=True)
class MutationDecision:
    """An admission result with enough context to give an actionable message."""

    verdict: MutationVerdict
    source_path: str | None = None
    reason: str | None = None
    next_action: str | None = None


_LINKED_REASON = "linked scene instance children are read-only; changes would not persist"
_LINKED_NEXT_ACTION = "Open the source scene or make this instance unique to edit local content"

# Operations that can be represented on the authored instance root's
# ``SceneInstanceComponent.overrides`` map (per-entity-name exposed values).
_OVERRIDE_OPERATIONS = frozenset({"set_exposed_value"})


def decide_entity_mutation(scene: Scene, entity_id: str, operation: str) -> MutationDecision:
    """Return the admission verdict for mutating ``entity_id`` with ``operation``."""
    try:
        origin = scene.entity_origin(entity_id)
    except KeyError:
        return MutationDecision(MutationVerdict.REJECT_LINKED, reason="entity no longer exists")
    if origin.kind != "materialized":
        return MutationDecision(MutationVerdict.ALLOW_AUTHORED)
    if operation in _OVERRIDE_OPERATIONS:
        return MutationDecision(
            MutationVerdict.ROUTE_INSTANCE_OVERRIDE,
            source_path=origin.source_path,
        )
    return MutationDecision(
        MutationVerdict.REJECT_LINKED,
        source_path=origin.source_path,
        reason=_LINKED_REASON,
        next_action=_LINKED_NEXT_ACTION,
    )


def route_instance_override_target(
    scene: Scene, entity_id: str
) -> tuple[Any, SceneInstanceComponent, str] | str:
    """Resolve the override target for a generated descendant's exposed-value edit.

    Returns ``(root_entity, component, entity_name)`` on success, or an
    ``str`` error message to surface instead. The edit is refused when the
    edited entity is not the first materialized entity with its name under its
    instance (matching ``SceneInstanceComponent.overrides``' first-name rule), so
    we never silently write an override that targets a different sibling.
    """
    origin = scene.entity_origin(entity_id)
    if origin.kind != "materialized" or origin.instance_root_id is None:
        return "not a linked scene instance child"
    root = scene.find_entity(origin.instance_root_id)
    component = root.get_component(SceneInstanceComponent) if root is not None else None
    if root is None or component is None:
        return "owning instance no longer references a source scene"
    entity = scene.find_entity(entity_id)
    if entity is None:
        return "entity no longer exists"
    first = next(
        (
            candidate
            for candidate in scene.entities
            if candidate.name == entity.name
            and scene.entity_origin(candidate.entity_id).instance_root_id == origin.instance_root_id
        ),
        None,
    )
    if first is None or first.entity_id != entity_id:
        return (
            f"name {entity.name!r} is shared by this instance; "
            "open the source scene or make this instance unique"
        )
    return root, component, entity.name


__all__ = (
    "MutationDecision",
    "MutationVerdict",
    "decide_entity_mutation",
    "route_instance_override_target",
)
