"""Serialized named anchors used by World graph connections."""

from __future__ import annotations

import pytest

from expra_engine.core.component import component_from_dict, registered_component_types
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Level


def test_level_anchor_is_a_registered_editable_component() -> None:
    data = {
        "type": "level_anchor",
        "enabled": True,
        "anchor_id": "north-gate",
        "kind": "exit",
        "shape": "rectangle",
        "size": [4.0, 8.0],
    }

    component = component_from_dict(data)
    registered = dict(registered_component_types())

    assert type(component).__name__ == "LevelAnchorComponent"
    assert component.to_dict() == data
    assert registered["level_anchor"] is type(component)
    assert {field.name for field in component_type_spec("level_anchor").fields} >= {
        "anchor_id", "kind", "shape", "size"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"anchor_id": "", "kind": "exit", "shape": "rectangle", "size": [2.0, 2.0]},
        {"anchor_id": "door", "kind": "teleport", "shape": "rectangle", "size": [2.0, 2.0]},
        {"anchor_id": "door", "kind": "exit", "shape": "triangle", "size": [2.0, 2.0]},
        {"anchor_id": "door", "kind": "exit", "shape": "circle", "size": [0.0, 2.0]},
    ],
)
def test_level_anchor_rejects_invalid_marker_data(payload: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        component_from_dict({"type": "level_anchor", "enabled": True, **payload})


def test_level_anchor_round_trips_as_an_ordinary_level_entity_component() -> None:
    level = Level("Town")
    gate = level.create_entity("North Gate", entity_id="gate")
    gate.add_component(
        component_from_dict(
            {
                "type": "level_anchor",
                "enabled": True,
                "anchor_id": "north",
                "kind": "both",
                "shape": "circle",
                "size": [3.0, 3.0],
            }
        )
    )

    restored = Level.from_dict(level.to_dict())

    assert restored.find_entity("gate") is not None
    restored_gate = restored.find_entity("gate")
    assert restored_gate is not None
    anchor = restored_gate.get_component(type(gate.components[-1]))
    assert anchor is not None
    assert anchor.to_dict()["anchor_id"] == "north"


def test_level_resolves_named_anchor_to_its_authored_entity() -> None:
    from expra_engine.runtime.level_anchor import LevelAnchorComponent

    level = Level("Town")
    gate = level.create_entity("North Gate", entity_id="gate")
    gate.add_component(LevelAnchorComponent("north", kind="exit"))

    resolved = level.find_anchor("north")

    assert resolved is not None
    assert resolved[0] is gate
    assert resolved[1].anchor_id == "north"
    assert level.find_anchor("missing") is None


def test_level_rejects_duplicate_anchor_ids() -> None:
    from expra_engine.runtime.level_anchor import LevelAnchorComponent

    level = Level("Town")
    for name in ("North Gate", "North Window"):
        level.create_entity(name).add_component(LevelAnchorComponent("north"))

    with pytest.raises(ValueError, match="duplicate Level anchor ID: 'north'"):
        level.validate_anchors()


def test_streaming_anchor_is_an_explicit_generic_entity_marker() -> None:
    component = component_from_dict(
        {"type": "streaming_anchor", "enabled": True, "anchor_id": "party_leader"}
    )

    assert type(component).__name__ == "StreamingAnchorComponent"
    assert component.to_dict() == {
        "type": "streaming_anchor",
        "enabled": True,
        "anchor_id": "party_leader",
    }


def test_persistent_actor_marker_has_stable_explicit_world_identity() -> None:
    component = component_from_dict(
        {"type": "world_persistent_actor", "enabled": True, "persistent_id": "courier"}
    )

    assert type(component).__name__ == "WorldPersistentActorComponent"
    assert component.to_dict() == {
        "type": "world_persistent_actor",
        "enabled": True,
        "persistent_id": "courier",
    }


def test_session_capture_component_is_an_explicit_json_state_opt_in() -> None:
    component = component_from_dict(
        {
            "type": "world_session_state",
            "enabled": True,
            "values": {"open": False, "uses_left": 2},
        }
    )

    assert type(component).__name__ == "WorldSessionStateComponent"
    assert component.to_dict()["values"] == {"open": False, "uses_left": 2}
