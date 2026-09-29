"""Canonical JSON/protobuf document codec tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import Level, LevelMetadata, document_codec
from expra_engine.core.scene.document_codec import (
    DocumentCodecError,
    canonical_pb_path,
    decode_protobuf,
    decode_protobuf_document,
    encode_protobuf,
    from_json,
    kind_for_document_path,
    to_json,
)
from expra_engine.schema.generated import common_pb2, level_pb2, scene_pb2


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


# ---------------------------------------------------------------------------
# Fail-closed value validation — unrepresentable or type-confused schema values
# ---------------------------------------------------------------------------


def _scene_document_with_payload(payload_value: object) -> dict[str, object]:
    return {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Values",
        "entities": [
            {
                "entity_id": "root",
                "name": "Root",
                "components": [{"type": "vendor.future", "payload": {"value": payload_value}}],
            }
        ],
    }


def test_encode_protobuf_rejects_integer_outside_int64_range() -> None:
    with pytest.raises(DocumentCodecError, match="int64"):
        encode_protobuf(_scene_document_with_payload(2**63))
    with pytest.raises(DocumentCodecError, match="int64"):
        encode_protobuf(_scene_document_with_payload(-(2**63) - 1))


def test_encode_protobuf_rejects_non_finite_float() -> None:
    with pytest.raises(DocumentCodecError, match="finite"):
        encode_protobuf(_scene_document_with_payload(float("nan")))
    with pytest.raises(DocumentCodecError, match="finite"):
        encode_protobuf(_scene_document_with_payload(float("inf")))


def test_to_json_rejects_non_finite_values() -> None:
    with pytest.raises(DocumentCodecError, match="finite"):
        to_json({"camera": {"zoom": float("nan")}})


def test_document_rejects_non_boolean_entity_enabled() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Values",
        "entities": [{"entity_id": "root", "name": "Root", "enabled": "false"}],
    }

    with pytest.raises(DocumentCodecError, match="enabled"):
        from_json(document)


def test_document_rejects_non_boolean_component_enabled() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Values",
        "entities": [
            {
                "entity_id": "root",
                "name": "Root",
                "components": [{"type": "transform", "enabled": 0, "x": 1.0}],
            }
        ],
    }

    with pytest.raises(DocumentCodecError, match="enabled"):
        from_json(document)


def test_document_rejects_bool_schema_version() -> None:
    document = {
        "kind": "scene",
        "scene_id": "scene-1",
        "name": "Values",
        "schema_version": True,
        "entities": [],
    }

    with pytest.raises(DocumentCodecError, match="schema_version"):
        from_json(document)
    with pytest.raises(DocumentCodecError, match="schema_version"):
        encode_protobuf(document)


def _foreign_nan_scene_payload() -> bytes:
    value = common_pb2.JsonValue()  # type: ignore[attr-defined]
    value.float_value = float("nan")
    payload = common_pb2.JsonObject()  # type: ignore[attr-defined]
    payload.values["value"].CopyFrom(value)
    component = common_pb2.Component()  # type: ignore[attr-defined]
    component.type_id = "vendor.future"
    component.payload.CopyFrom(payload)
    component.payload_explicit = True
    entity = common_pb2.Entity()  # type: ignore[attr-defined]
    entity.entity_id = "root"
    entity.name = "Root"
    entity.components.add().CopyFrom(component)
    scene = scene_pb2.SceneDocument()  # type: ignore[attr-defined]
    scene.schema_version = 1
    scene.document_kind = "scene"
    scene.scene_id = "scene-1"
    scene.name = "Values"
    scene.entities.add().CopyFrom(entity)
    envelope = level_pb2.DocumentEnvelope()  # type: ignore[attr-defined]
    envelope.scene.CopyFrom(scene)
    return envelope.SerializeToString(deterministic=True)


def test_decode_protobuf_rejects_non_finite_float() -> None:
    with pytest.raises(DocumentCodecError, match="finite"):
        decode_protobuf(_foreign_nan_scene_payload())


# ---------------------------------------------------------------------------
# canonical_pb_path — typed suffix normalisation
# ---------------------------------------------------------------------------


class TestCanonicalPbPathScene:
    def test_bare_name(self) -> None:
        assert canonical_pb_path("enemy", DocumentKind.SCENE) == "enemy.scene.pb"

    def test_bare_kind_suffix(self) -> None:
        assert canonical_pb_path("enemy.scene", DocumentKind.SCENE) == "enemy.scene.pb"

    def test_typed_json(self) -> None:
        assert canonical_pb_path("enemy.scene.json", DocumentKind.SCENE) == "enemy.scene.pb"

    def test_canonical_pb_idempotent(self) -> None:
        assert canonical_pb_path("enemy.scene.pb", DocumentKind.SCENE) == "enemy.scene.pb"

    def test_generic_json(self) -> None:
        assert canonical_pb_path("enemy.json", DocumentKind.SCENE) == "enemy.scene.pb"

    def test_preserves_directory(self) -> None:
        assert (
            canonical_pb_path("scenes/enemy.scene.json", DocumentKind.SCENE)
            == "scenes/enemy.scene.pb"
        )

    def test_no_doubled_suffix_from_typed_json(self) -> None:
        result = canonical_pb_path("enemy.scene.json", DocumentKind.SCENE)
        assert result == "enemy.scene.pb"
        assert "scene.scene" not in result

    def test_no_doubled_suffix_from_bare_kind(self) -> None:
        result = canonical_pb_path("enemy.scene", DocumentKind.SCENE)
        assert "scene.scene" not in result

    def test_repeated_application_stable(self) -> None:
        first = canonical_pb_path("enemy.scene.json", DocumentKind.SCENE)
        second = canonical_pb_path(first, DocumentKind.SCENE)
        assert first == second == "enemy.scene.pb"


class TestCanonicalPbPathLevel:
    def test_bare_name(self) -> None:
        assert canonical_pb_path("forest", DocumentKind.LEVEL) == "forest.level.pb"

    def test_bare_kind_suffix(self) -> None:
        assert canonical_pb_path("forest.level", DocumentKind.LEVEL) == "forest.level.pb"

    def test_typed_json(self) -> None:
        assert canonical_pb_path("forest.level.json", DocumentKind.LEVEL) == "forest.level.pb"

    def test_canonical_pb_idempotent(self) -> None:
        assert canonical_pb_path("forest.level.pb", DocumentKind.LEVEL) == "forest.level.pb"

    def test_generic_json(self) -> None:
        assert canonical_pb_path("forest.json", DocumentKind.LEVEL) == "forest.level.pb"

    def test_preserves_directory(self) -> None:
        assert (
            canonical_pb_path("levels/chapter_one.level.json", DocumentKind.LEVEL)
            == "levels/chapter_one.level.pb"
        )

    def test_no_doubled_suffix_from_typed_json(self) -> None:
        result = canonical_pb_path("forest.level.json", DocumentKind.LEVEL)
        assert result == "forest.level.pb"
        assert "level.level" not in result

    def test_no_doubled_suffix_from_bare_kind(self) -> None:
        result = canonical_pb_path("forest.level", DocumentKind.LEVEL)
        assert "level.level" not in result

    def test_repeated_application_stable(self) -> None:
        first = canonical_pb_path("forest.level.json", DocumentKind.LEVEL)
        second = canonical_pb_path(first, DocumentKind.LEVEL)
        assert first == second == "forest.level.pb"


class TestCanonicalPbPathWorld:
    def test_bare_name(self) -> None:
        assert canonical_pb_path("main", DocumentKind.WORLD) == "main.world.pb"

    def test_bare_kind_suffix(self) -> None:
        assert canonical_pb_path("main.world", DocumentKind.WORLD) == "main.world.pb"

    def test_typed_json(self) -> None:
        assert canonical_pb_path("main.world.json", DocumentKind.WORLD) == "main.world.pb"

    def test_canonical_pb_idempotent(self) -> None:
        assert canonical_pb_path("main.world.pb", DocumentKind.WORLD) == "main.world.pb"

    def test_generic_json(self) -> None:
        assert canonical_pb_path("main.json", DocumentKind.WORLD) == "main.world.pb"

    def test_preserves_directory(self) -> None:
        assert (
            canonical_pb_path("worlds/main.world.json", DocumentKind.WORLD)
            == "worlds/main.world.pb"
        )

    def test_no_doubled_suffix_from_typed_json(self) -> None:
        result = canonical_pb_path("main.world.json", DocumentKind.WORLD)
        assert result == "main.world.pb"
        assert "world.world" not in result

    def test_no_doubled_suffix_from_bare_kind(self) -> None:
        result = canonical_pb_path("main.world", DocumentKind.WORLD)
        assert "world.world" not in result

    def test_repeated_application_stable(self) -> None:
        first = canonical_pb_path("main.world.json", DocumentKind.WORLD)
        second = canonical_pb_path(first, DocumentKind.WORLD)
        assert first == second == "main.world.pb"


class TestCanonicalPbPathNegative:
    """Assert that no operation through canonical_pb_path produces doubled type suffixes."""

    def test_scene_never_produces_doubled_suffix(self) -> None:
        for name in ("x.scene", "x.scene.json", "x.scene.pb", "x"):
            result = canonical_pb_path(name, DocumentKind.SCENE)
            assert "scene.scene" not in result, f"doubled suffix in {result!r} from {name!r}"

    def test_level_never_produces_doubled_suffix(self) -> None:
        for name in ("x.level", "x.level.json", "x.level.pb", "x"):
            result = canonical_pb_path(name, DocumentKind.LEVEL)
            assert "level.level" not in result, f"doubled suffix in {result!r} from {name!r}"

    def test_world_never_produces_doubled_suffix(self) -> None:
        for name in ("x.world", "x.world.json", "x.world.pb", "x"):
            result = canonical_pb_path(name, DocumentKind.WORLD)
            assert "world.world" not in result, f"doubled suffix in {result!r} from {name!r}"
