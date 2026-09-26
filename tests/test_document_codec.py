"""Canonical JSON/protobuf document codec tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Level, LevelMetadata, document_codec
from expra_engine.core.scene.document_codec import (
    DocumentCodecError,
    decode_protobuf,
    decode_protobuf_document,
    encode_protobuf,
    from_json,
    kind_for_document_path,
    to_json,
)


def _level() -> Level:
    level = Level(
        "Deepcore",
        scene_id="level-1",
        level_metadata=LevelMetadata(
            display_name="Deepcore",
            world_bounds=(-10.0, -5.0, 100.0, 50.0),
            spawn_entity_id="player",
            default_camera_id="camera",
            tags=("campaign", "underground"),
        ),
    )
    level.camera["target_entity_id"] = "player"
    player = level.create_entity("Player", entity_id="player")
    player.add_component(TransformComponent(x=1.0, y=2.0, scale_x=3.0))
    level.create_entity("Weapon", entity_id="weapon", parent_id="player")
    return level


def test_json_round_trip_preserves_typed_level_and_order() -> None:
    original = _level()

    restored = from_json(to_json(original))

    assert isinstance(restored, Level)
    assert [entity.entity_id for entity in restored.entities] == ["player", "weapon"]
    assert restored.entities[1].parent_id == "player"
    assert restored.level_metadata.world_bounds == (-10.0, -5.0, 100.0, 50.0)
    assert restored.camera.target_entity_id == "player"


def test_protobuf_round_trip_preserves_recursive_values_and_int_float_distinction() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Values",
        "camera": {"target_entity_id": "root"},
        "entities": [
            {
                "entity_id": "root",
                "name": "Root",
                "enabled": True,
                "layer": 2,
                "parent_id": None,
                "tags": ["one"],
                "components": [
                    {
                        "type": "vendor.future",
                        "enabled": True,
                        "payload": {"count": 3, "ratio": 3.0, "nested": {"ok": False}},
                    }
                ],
            }
        ],
    }

    restored = decode_protobuf(encode_protobuf(document))

    assert restored == document
    assert type(restored["entities"][0]["components"][0]["payload"]["count"]) is int
    assert type(restored["entities"][0]["components"][0]["payload"]["ratio"]) is float


def test_protobuf_bytes_are_deterministic_and_json_is_stable() -> None:
    first = encode_protobuf(to_json(_level()))
    second = encode_protobuf(json.loads(json.dumps(to_json(_level()), sort_keys=True)))

    assert first == second
    assert to_json(_level()) == to_json(from_json(to_json(_level())))


def test_checked_in_bindings_are_reproducible() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "tools/generate_protobuf.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_typed_protobuf_extensions_match_decoded_document_kind() -> None:
    scene = _level()
    with pytest.raises(DocumentCodecError, match="scene document"):
        decode_protobuf_document(encode_protobuf(scene), expected_kind="scene")

    level_payload = encode_protobuf(scene)
    loaded = decode_protobuf_document(level_payload, expected_kind="level")
    assert isinstance(loaded, Level)


def test_protobuf_document_requires_supported_version_and_logical_identity() -> None:
    document = {"kind": "scene", "scene_id": "", "name": "", "entities": []}
    with pytest.raises(DocumentCodecError, match="scene_id"):
        decode_protobuf_document(encode_protobuf(document))


def test_json_document_rejects_entity_missing_required_name() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Malformed",
        "entities": [{"entity_id": "entity-1", "components": []}],
    }

    with pytest.raises(DocumentCodecError, match=r"entity.*name"):
        from_json(document)


def test_json_document_rejects_dangling_parent() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Malformed",
        "entities": [{"entity_id": "entity-1", "name": "Child", "parent_id": "missing"}],
    }

    with pytest.raises(DocumentCodecError, match="parent"):
        from_json(document)


def test_json_document_rejects_hierarchy_cycle() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Malformed",
        "entities": [
            {"entity_id": "entity-1", "name": "One", "parent_id": "entity-2"},
            {"entity_id": "entity-2", "name": "Two", "parent_id": "entity-1"},
        ],
    }

    with pytest.raises(DocumentCodecError, match="cycle"):
        from_json(document)


def test_json_document_rejects_invalid_known_component_payload() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Malformed",
        "entities": [
            {
                "entity_id": "entity-1",
                "name": "Entity",
                "components": [{"type": "transform", "x": "not-a-number"}],
            }
        ],
    }

    with pytest.raises(DocumentCodecError, match="invalid Scene document"):
        from_json(document)


def test_level_document_rejects_non_sequence_world_bounds() -> None:
    document = {
        "kind": "level",
        "scene_id": "level-1",
        "name": "Malformed",
        "level_metadata": {"world_bounds": 42},
        "entities": [],
    }

    with pytest.raises(DocumentCodecError, match="world_bounds"):
        from_json(document)


def test_owned_document_data_builder_does_not_copy_decoded_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {"kind": "scene", "scene_id": "scene-1", "name": "Owned", "entities": []}

    monkeypatch.setattr(
        "expra_engine.core.scene.document_codec.deepcopy",
        lambda _value: pytest.fail("owned decoded data must not be copied"),
    )

    loaded = document_codec.from_document_data(document)

    assert loaded.scene_id == "scene-1"


def test_document_path_kind_recognizes_typed_and_legacy_extensions() -> None:
    assert kind_for_document_path("scenes/door.scene.pb") == "scene"
    assert kind_for_document_path("levels/deepcore.level.pb") == "level"
    assert kind_for_document_path("scenes/door.json") is None
    with pytest.raises(DocumentCodecError, match="typed"):
        kind_for_document_path("data/document.pb")
