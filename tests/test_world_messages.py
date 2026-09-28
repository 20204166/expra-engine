"""Canonical World diagnostic wording remains parameterized and engine-neutral."""

from __future__ import annotations

import importlib
import importlib.util


def test_world_message_builders_own_startup_and_transition_wording() -> None:
    package_spec = importlib.util.find_spec("expra_engine.messages")
    assert package_spec is not None, "core/runtime diagnostic wording has no canonical owner"
    messages = importlib.import_module("expra_engine.messages.world")

    assert messages.initial_entrance_without_primary_anchor("start") == (
        "World initial entrance 'start' is configured, but primary_anchor_id is not set; "
        "actor placement/travel cannot be established"
    )
    assert messages.primary_anchor_missing("player", "transit_district") == (
        "World primary anchor 'player' is not present in the active startup Level "
        "'transit_district'; the Level remains active for rendering"
    )
    assert messages.primary_anchor_not_persistent("player") == (
        "World primary anchor 'player' is not attached to an active "
        "World-persistent actor; the Level remains active for rendering"
    )
    assert messages.initial_entrance_invalid("start", "transit_district") == (
        "World initial entrance 'start' is not an entrance anchor in Level 'transit_district'"
    )
    assert messages.duplicate_level_anchor("north") == "duplicate Level anchor ID: 'north'"
    assert (
        messages.duplicate_persistent_actor("courier") == "duplicate persistent actor ID: 'courier'"
    )
    assert messages.persistent_actor_declared_by_multiple_levels("courier") == (
        "persistent actor ID 'courier' is declared by multiple Levels"
    )
    assert messages.destination_level_waiting("bell_market") == (
        "waiting for destination Level 'bell_market'"
    )
    assert messages.destination_level_failed_retry("bell_market") == (
        "destination Level 'bell_market' failed to load; retry explicitly"
    )
    assert messages.destination_level_over_residency_budget("bell_market", "budget full") == (
        "connection destination 'bell_market' is blocked by the World residency budget: budget full"
    )
    assert messages.pending_destination_over_residency_budget("budget full") == (
        "pending seamless travel exceeds World residency budget: budget full"
    )


def test_world_message_builders_keep_failure_context_bounded_and_specific() -> None:
    package_spec = importlib.util.find_spec("expra_engine.messages")
    assert package_spec is not None, "core/runtime diagnostic wording has no canonical owner"
    messages = importlib.import_module("expra_engine.messages.world")

    assert messages.startup_level_load_failed("town", "ProjectError", "missing level") == (
        "World startup Level 'town' failed to load: ProjectError: missing level"
    )
    assert messages.level_activation_failed("town", "RuntimeError", "hook failed") == (
        "Level 'town' activation failed: RuntimeError: hook failed"
    )
    assert messages.destination_anchor_missing("gate") == (
        "connection 'gate' destination anchor is missing"
    )


def test_world_diagnostics_bound_untrusted_authored_identifiers() -> None:
    spec = importlib.util.find_spec("expra_engine.messages.world")
    assert spec is not None
    messages = importlib.import_module("expra_engine.messages.world")

    message = messages.primary_anchor_missing("a" * 10000, "b" * 10000)

    assert len(message) <= 400
    assert "..." in message
    assert messages.world_travel_requires_actor_at_exit() == (
        "seamless travel requires the actor to be at the connected exit"
    )
    assert messages.seamless_connection_not_adjacent() == (
        "seamless connection endpoints are not physically adjacent"
    )
    assert messages.destination_level_activation_failed("bell_market") == (
        "destination Level 'bell_market' could not activate"
    )
    assert messages.world_travel_anchor_required() == (
        "World travel requires a registered streaming anchor"
    )
    assert messages.streaming_anchor_unavailable("player") == (
        "streaming anchor is unavailable: player"
    )
    assert messages.connection_unreachable("transit_district") == (
        "connection is not reachable from Level 'transit_district'"
    )
    assert messages.world_persistent_actor_inactive() == (
        "World-persistent actor is no longer active"
    )
    assert messages.transition_commit_failed("RuntimeError", "hook failed") == (
        "RuntimeError: hook failed"
    )
