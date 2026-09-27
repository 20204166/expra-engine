"""Typed World document, graph validation, and protobuf integration tests."""

from __future__ import annotations

import importlib.util

import pytest

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene.document_codec import (
    decode_protobuf_document,
    encode_protobuf,
    kind_for_document_path,
)
from expra_engine.core.world import World


def _world_types():
    from expra_engine.core.world import (
        LevelDescriptor,
        TransitionMode,
        World,
        WorldConnection,
        WorldStreamingSettings,
    )

    return LevelDescriptor, TransitionMode, World, WorldConnection, WorldStreamingSettings


def make_world() -> World:
    LevelDescriptor, TransitionMode, World, WorldConnection, WorldStreamingSettings = _world_types()
    return World(
        "Vey",
        world_id="vey",
        levels=(
            LevelDescriptor("centre", "levels/centre.level.pb", origin=(0.0, 0.0)),
            LevelDescriptor("residential", "levels/residential.level.pb", origin=(200.0, 0.0)),
        ),
        connections=(
            WorldConnection(
                "north-gate",
                "centre",
                "north-exit",
                "residential",
                "south-entry",
                bidirectional=True,
                transition=TransitionMode.SEAMLESS,
                preload_distance=24.0,
                unload_distance=48.0,
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="centre",
        initial_entrance_id="arrival",
        streaming=WorldStreamingSettings(max_concurrent_loads=2, max_loaded_levels=6),
    )


def test_world_protobuf_round_trip_is_typed_and_deterministic() -> None:
    world = make_world()

    payload = encode_protobuf(world)
    restored = decode_protobuf_document(payload, expected_kind=DocumentKind.WORLD)

    assert restored == world
    assert encode_protobuf(restored) == payload
    assert kind_for_document_path("worlds/vey.world.pb") is DocumentKind.WORLD


def test_world_kind_is_a_first_class_document_kind() -> None:
    assert getattr(DocumentKind, "WORLD", None) == "world"


def test_world_document_path_is_classified_as_world() -> None:
    result = kind_for_document_path("worlds/vey.world.pb")
    assert result is DocumentKind.WORLD


def test_world_domain_has_a_canonical_core_module() -> None:
    assert importlib.util.find_spec("expra_engine.core.world") is not None


def test_world_domain_exposes_one_graph_and_descriptor_model() -> None:
    from importlib import import_module

    module = import_module("expra_engine.core.world")

    assert all(
        hasattr(module, name)
        for name in (
            "LevelDescriptor",
            "TransitionMode",
            "World",
            "WorldConnection",
            "WorldStreamingSettings",
        )
    )


def test_world_is_exported_from_the_core_public_api() -> None:
    import expra_engine.core as core

    _, _, World, _, _ = _world_types()
    assert getattr(core, "World", None) is World


def test_world_connections_are_directed_unless_marked_bidirectional() -> None:
    world = make_world()

    assert tuple(item.connection_id for item in world.connections_from("centre")) == (
        "north-gate",
    )
    assert tuple(item.connection_id for item in world.connections_from("residential")) == (
        "north-gate:reverse",
    )
    assert tuple(item.connection_id for item in world.connections_to("residential")) == (
        "north-gate",
    )
    assert tuple(item.connection_id for item in world.connections_to("centre")) == (
        "north-gate:reverse",
    )
    reverse = world.connections_from("residential", include_reverse=True)[0]
    assert reverse.source_level_id == "residential"
    assert reverse.destination_level_id == "centre"
    assert reverse.source_anchor_id == "south-entry"
    assert reverse.destination_anchor_id == "north-exit"


def test_legacy_bidirectional_connection_is_migrated_to_two_explicit_directed_edges() -> None:
    _, _, World, _, _ = _world_types()
    world = make_world()

    assert len(world.connections) == 2
    assert all(not connection.bidirectional for connection in world.connections)
    assert {connection.connection_id for connection in world.connections} == {
        "north-gate",
        "north-gate:reverse",
    }
    restored = World.from_dict(world.to_dict())
    assert restored == world


@pytest.mark.parametrize(
    "invalid_case",
    ["duplicate-level", "missing-level", "unsafe-path", "non-finite-origin", "hysteresis"],
)
def test_world_rejects_invalid_graph_paths_and_bounds(invalid_case: str) -> None:
    LevelDescriptor, _TransitionMode, World, WorldConnection, _WorldStreamingSettings = _world_types()
    world = make_world()
    with pytest.raises(ValueError):
        values: dict[str, object] = {
            "levels": world.levels,
            "connections": world.connections,
            "initial_level_id": "centre",
            "initial_entrance_id": "arrival",
        }
        if invalid_case == "duplicate-level":
            values["levels"] = (
                LevelDescriptor("same", "levels/a.level.pb"),
                LevelDescriptor("same", "levels/b.level.pb"),
            )
        elif invalid_case == "missing-level":
            values["connections"] = (
                WorldConnection("bad", "missing", "exit", "other", "entry"),
            )
        elif invalid_case == "unsafe-path":
            values["levels"] = (LevelDescriptor("bad", "../outside.level.pb"),)
        elif invalid_case == "non-finite-origin":
            values["levels"] = (
                LevelDescriptor("bad", "levels/a.level.pb", origin=(float("nan"), 0.0)),
            )
        else:
            values["connections"] = (
                WorldConnection(
                    "bad", "centre", "exit", "residential", "entry",
                    preload_distance=50.0, unload_distance=50.0,
                ),
            )
        World("Invalid", world_id="invalid", **values)  # type: ignore[arg-type]


def test_world_rejects_duplicate_connection_ids_and_bad_initial_level() -> None:
    _LevelDescriptor, _TransitionMode, World, _WorldConnection, _WorldStreamingSettings = _world_types()
    valid = make_world()
    duplicate = valid.connections[0]

    with pytest.raises(ValueError, match="connection"):
        World(
            "Duplicate",
            world_id="duplicate",
            levels=valid.levels,
            connections=(duplicate, duplicate),
            initial_level_id="centre",
            initial_entrance_id="arrival",
        )

    with pytest.raises(ValueError, match="initial"):
        World(
            "Missing entry",
            world_id="missing-entry",
            levels=valid.levels,
            initial_level_id="missing",
            initial_entrance_id="arrival",
        )


def test_world_resident_budget_includes_starting_level_and_always_loaded_levels() -> None:
    LevelDescriptor, _TransitionMode, World, _WorldConnection, WorldStreamingSettings = _world_types()

    with pytest.raises(ValueError, match="max_loaded_levels"):
        World(
            "Over budget at startup",
            world_id="over-budget",
            levels=(
                LevelDescriptor("start", "levels/start.level.pb"),
                LevelDescriptor("ambient", "levels/ambient.level.pb", always_loaded=True),
            ),
            initial_level_id="start",
            streaming=WorldStreamingSettings(max_loaded_levels=1),
        )
