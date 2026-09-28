"""Human-readable World streaming, startup, and transition diagnostics."""

from __future__ import annotations

from expra_engine.messages._format import bounded_repr, bounded_text


def world_resource_not_level(resource_path: str) -> str:
    return f"World resource {bounded_repr(resource_path)} did not contain a Level"


def initial_entrance_invalid(entrance_id: str, level_id: str) -> str:
    return (
        f"World initial entrance {bounded_repr(entrance_id)} is not an entrance anchor "
        f"in Level {bounded_repr(level_id)}"
    )


def startup_level_load_failed(level_id: str, error_type: str, detail: str) -> str:
    return (
        f"World startup Level {bounded_repr(level_id)} failed to load: "
        f"{bounded_text(error_type, 80)}: {bounded_text(detail)}"
    )


def level_activation_failed(level_id: str, error_type: str, detail: str) -> str:
    return (
        f"Level {bounded_repr(level_id)} activation failed: "
        f"{bounded_text(error_type, 80)}: {bounded_text(detail, 160)}"
    )


def initial_entrance_without_primary_anchor(entrance_id: str) -> str:
    return (
        f"World initial entrance {bounded_repr(entrance_id)} is configured, "
        "but primary_anchor_id is not set; "
        "actor placement/travel cannot be established"
    )


def primary_anchor_missing(anchor_id: str, startup_level_id: str | None) -> str:
    return (
        f"World primary anchor {bounded_repr(anchor_id)} is not present in the active startup Level "
        f"{bounded_repr(startup_level_id)}; the Level remains active for rendering"
    )


def primary_anchor_not_persistent(anchor_id: str) -> str:
    return (
        f"World primary anchor {bounded_repr(anchor_id)} is not attached to an active "
        "World-persistent actor; the Level remains active for rendering"
    )


def duplicate_persistent_actor(persistent_id: str) -> str:
    return f"duplicate persistent actor ID: {bounded_repr(persistent_id)}"


def persistent_actor_declared_by_multiple_levels(persistent_id: str) -> str:
    return f"persistent actor ID {bounded_repr(persistent_id)} is declared by multiple Levels"


def persistent_actor_source_level_changed(persistent_id: str) -> str:
    return f"persistent actor {bounded_repr(persistent_id)} source Level changed"


def streaming_anchor_unknown_level(level_id: str) -> str:
    return f"streaming anchor references an unknown Level: {bounded_repr(level_id)}"


def duplicate_streaming_anchor(anchor_id: str) -> str:
    return f"duplicate World streaming anchor ID: {bounded_repr(anchor_id)}"


def duplicate_level_anchor(anchor_id: str) -> str:
    return f"duplicate Level anchor ID: {bounded_repr(anchor_id)}"


def duplicate_active_level_anchor(level_id: str, anchor_id: str) -> str:
    return f"duplicate active Level anchor: ({bounded_repr(level_id)}, {bounded_repr(anchor_id)})"


def world_level_pinned(level_id: str) -> str:
    return f"World Level {bounded_repr(level_id)} is pinned; unpin it before unloading"


def world_travel_anchor_required() -> str:
    return "World travel requires a registered streaming anchor"


def streaming_anchor_unavailable(anchor_id: str) -> str:
    return f"streaming anchor is unavailable: {bounded_text(anchor_id, 120)}"


def connection_unreachable(level_id: str) -> str:
    return f"connection is not reachable from Level {bounded_repr(level_id)}"


def world_travel_requires_persistent_actor() -> str:
    return "World travel requires an active World-persistent actor"


def world_travel_source_anchor_inactive() -> str:
    return "World travel source anchor is not active"


def world_travel_source_anchor_not_exit() -> str:
    return "World travel source anchor is not a connected exit"


def world_travel_requires_actor_at_exit() -> str:
    return "seamless travel requires the actor to be at the connected exit"


def pending_transition_data_lost() -> str:
    return "pending transition data was lost"


def destination_level_failed_to_load() -> str:
    return "destination Level failed to load"


def destination_level_failed_retry(level_id: str) -> str:
    return f"destination Level {bounded_repr(level_id)} failed to load; retry explicitly"


def destination_level_waiting(level_id: str) -> str:
    return f"waiting for destination Level {bounded_repr(level_id)}"


def pending_connection_source_anchor_lost(connection_id: str) -> str:
    return f"pending connection {bounded_repr(connection_id)} lost its source anchor"


def connection_source_anchor_not_exit(connection_id: str) -> str:
    return f"connection {bounded_repr(connection_id)} source anchor is not an exit"


def destination_anchor_missing(connection_id: str) -> str:
    return f"connection {bounded_repr(connection_id)} destination anchor is missing"


def seamless_connection_not_adjacent() -> str:
    return "seamless connection endpoints are not physically adjacent"


def world_persistent_actor_inactive() -> str:
    return "World-persistent actor is no longer active"


def destination_level_activation_failed(level_id: str) -> str:
    return f"destination Level {bounded_repr(level_id)} could not activate"


def destination_level_over_residency_budget(level_id: str, detail: str) -> str:
    return (
        f"connection destination {bounded_repr(level_id)} is blocked by the World residency budget: "
        f"{bounded_text(detail)}"
    )


def pending_destination_over_residency_budget(detail: str) -> str:
    return f"pending seamless travel exceeds World residency budget: {bounded_text(detail)}"


def transition_commit_failed(error_type: str, detail: str) -> str:
    return f"{bounded_text(error_type, 80)}: {bounded_text(detail, 180)}"
