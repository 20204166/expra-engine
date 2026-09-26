"""Canonical deterministic protobuf documents with a legacy JSON import path."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from google.protobuf.message import DecodeError

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import Level, Scene
from expra_engine.observability import ObservabilityWatcher
from expra_engine.schema.generated import common_pb2, level_pb2

CURRENT_DOCUMENT_SCHEMA_VERSION = 1


class DocumentCodecError(ValueError):
    """Raised when a Scene/Level document is malformed or incompatible."""


def kind_for_document_path(path: str | Path) -> DocumentKind | None:
    """Infer kind only from explicit typed extensions; legacy JSON stays untyped."""
    value = str(path).casefold()
    for suffix, kind in (
        (".scene.pb", DocumentKind.SCENE),
        (".scene.json", DocumentKind.SCENE),
        (".level.pb", DocumentKind.LEVEL),
        (".level.json", DocumentKind.LEVEL),
    ):
        if value.endswith(suffix):
            return kind
    if value.endswith(".pb"):
        raise DocumentCodecError(
            "protobuf document path must use a typed .scene.pb or .level.pb extension"
        )
    if value.endswith(".json"):
        return None
    raise DocumentCodecError(f"unsupported Scene/Level document extension: {path!s}")


def to_json(document: Scene | dict[str, Any]) -> dict[str, Any]:
    """Return the stable, JSON-friendly authoring representation."""
    data = document.to_dict() if isinstance(document, Scene) else deepcopy(document)
    return json.loads(json.dumps(data, sort_keys=True, separators=(",", ":")))


def from_json(document: str | dict[str, Any]) -> Scene:
    """Load a Scene or Level from the canonical JSON representation."""
    try:
        data = json.loads(document) if isinstance(document, str) else document
    except json.JSONDecodeError as exc:
        raise DocumentCodecError("legacy JSON document is malformed") from exc
    return from_document_data(data, copy_data=isinstance(document, dict))


def from_document_data(
    data: dict[str, Any],
    *,
    validate: bool = True,
    copy_data: bool = False,
    observer: ObservabilityWatcher | None = None,
) -> Scene:
    """Construct a Scene/Level from owned decoded data through one path."""
    if not isinstance(data, dict):
        raise DocumentCodecError("document must contain a JSON object")
    working = deepcopy(data) if copy_data else data
    kind = working.get("kind", DocumentKind.SCENE.value)
    if not isinstance(kind, str):
        raise DocumentCodecError("document kind must be a string")
    if validate:
        _validate_document_data(working, kind)
    if kind not in {DocumentKind.LEVEL.value, DocumentKind.SCENE.value}:
        raise DocumentCodecError(f"unsupported document kind: {kind!r}")
    try:
        if kind == DocumentKind.LEVEL.value:
            return Level.from_dict(working, observer=observer)
        return Scene.from_dict(working, observer=observer)
    except (TypeError, KeyError, ValueError) as exc:
        raise DocumentCodecError(f"invalid {kind.title()} document: {exc}") from exc


def decode_json_payload(payload: bytes) -> dict[str, Any]:
    """Parse legacy JSON bytes without constructing the document model."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentCodecError("legacy JSON document is malformed") from exc
    if not isinstance(data, dict):
        raise DocumentCodecError("document must contain a JSON object")
    return data


def parse_protobuf(payload: bytes) -> Any:
    """Parse protobuf wire data into the generated message representation."""
    envelope = level_pb2.DocumentEnvelope()  # type: ignore[attr-defined]
    try:
        envelope.ParseFromString(payload)
    except DecodeError as exc:
        raise DocumentCodecError("corrupt protobuf document") from exc
    return envelope


def protobuf_to_document_data(envelope: Any) -> dict[str, Any]:
    """Convert a generated protobuf message into canonical document data."""
    document_field = envelope.WhichOneof("document")
    if document_field == "level":
        if not envelope.level.HasField("scene"):
            raise DocumentCodecError("LevelDocument is missing its Scene graph")
        if not envelope.level.HasField("metadata"):
            raise DocumentCodecError("LevelDocument is missing required level metadata")
        data = _level_to_dict(envelope.level)
    elif document_field == "scene":
        data = _scene_to_dict(envelope.scene)
    else:
        raise DocumentCodecError("protobuf document envelope is empty")
    _validate_document_data(data, data.get("kind", "scene"))
    return data


def encode_protobuf(document: Scene | dict[str, Any]) -> bytes:
    """Encode a document deterministically using the checked-in schema."""
    data = to_json(document)
    kind = data.get("kind", DocumentKind.SCENE.value)
    _validate_document_data(data, kind)
    envelope = level_pb2.DocumentEnvelope()  # type: ignore[attr-defined]
    if kind == DocumentKind.LEVEL.value:
        _fill_level(envelope.level, data)
    elif kind == DocumentKind.SCENE.value:
        _fill_scene(envelope.scene, data)
    else:
        raise ValueError(f"unsupported document kind: {kind!r}")
    return envelope.SerializeToString(deterministic=True)


def decode_protobuf(payload: bytes) -> dict[str, Any]:
    """Decode protobuf bytes into the canonical JSON-friendly dictionary."""
    return protobuf_to_document_data(parse_protobuf(payload))


def decode_protobuf_document(
    payload: bytes, *, expected_kind: DocumentKind | str | None = None
) -> Scene:
    """Decode, validate a typed kind, and construct the canonical model."""
    data = decode_protobuf(payload)
    actual_kind = DocumentKind(data["kind"])
    if expected_kind is not None and actual_kind != DocumentKind(expected_kind):
        raise DocumentCodecError(
            f"expected a {DocumentKind(expected_kind).value} document, found {actual_kind.value}"
        )
    return from_document_data(data, validate=False)


def document_to_protobuf(document: Scene) -> bytes:
    """Serialize the model directly to its canonical deterministic PB bytes."""
    return encode_protobuf(document)


def document_from_path_bytes(
    payload: bytes,
    path: str | Path,
    *,
    expected_kind: DocumentKind | str | None = None,
) -> Scene:
    """Decode typed PB or compatibility JSON bytes, validating typed suffixes."""
    extension_kind = kind_for_document_path(path)
    expected = DocumentKind(expected_kind) if expected_kind is not None else extension_kind
    if extension_kind is not None and expected is not None and extension_kind != expected:
        raise DocumentCodecError(
            f"document extension declares {extension_kind.value}, registry declares {expected.value}"
        )
    if str(path).casefold().endswith(".pb"):
        return decode_protobuf_document(payload, expected_kind=expected)
    data = decode_json_payload(payload)
    stored_kind = data.get("kind")
    if stored_kind is None and expected is not None:
        data["kind"] = expected.value
    elif expected is not None and stored_kind != expected.value:
        raise DocumentCodecError(f"expected a {expected.value} document, found {stored_kind!r}")
    document = from_document_data(data)
    actual_kind = document.document_kind
    if expected is not None and actual_kind != expected:
        raise DocumentCodecError(f"expected a {expected.value} document, found {actual_kind.value}")
    return document


def _validate_document_data(data: dict[str, Any], kind: str) -> None:
    if kind not in {DocumentKind.SCENE.value, DocumentKind.LEVEL.value}:
        raise DocumentCodecError(f"unsupported document kind: {kind!r}")
    if not isinstance(data.get("scene_id"), str) or not data["scene_id"].strip():
        raise DocumentCodecError("document requires a non-empty scene_id")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise DocumentCodecError("document requires a non-empty name")
    version = data.get("schema_version", CURRENT_DOCUMENT_SCHEMA_VERSION)
    if not isinstance(version, int) or version < 1:
        raise DocumentCodecError("document schema_version must be a positive integer")
    if version > CURRENT_DOCUMENT_SCHEMA_VERSION:
        raise DocumentCodecError(f"unsupported future document schema: {version}")
    if kind == DocumentKind.LEVEL.value:
        metadata = data.get("level_metadata")
        if not isinstance(metadata, dict):
            raise DocumentCodecError("Level document requires level_metadata")
        bounds = metadata.get("world_bounds")
        if bounds is not None and (not isinstance(bounds, (list, tuple)) or len(bounds) != 4):
            raise DocumentCodecError("Level world_bounds must contain four values")
    entities = data.get("entities", [])
    if not isinstance(entities, list):
        raise DocumentCodecError("document entities must be a list")
    entity_ids: set[str] = set()
    parent_ids: dict[str, str | None] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            raise DocumentCodecError("each entity must be an object")
        entity_id = entity.get("entity_id")
        name = entity.get("name")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise DocumentCodecError("each entity requires a non-empty entity_id")
        if not isinstance(name, str) or not name.strip():
            raise DocumentCodecError(f"entity {entity_id!r} requires a non-empty name")
        if entity_id in entity_ids:
            raise DocumentCodecError(f"duplicate entity_id: {entity_id!r}")
        entity_ids.add(entity_id)
        parent_id = entity.get("parent_id")
        if parent_id is not None and (not isinstance(parent_id, str) or not parent_id.strip()):
            raise DocumentCodecError(f"entity {entity_id!r} has an invalid parent_id")
        parent_ids[entity_id] = parent_id
        components = entity.get("components", [])
        if not isinstance(components, list):
            raise DocumentCodecError(f"entity {entity_id!r} components must be a list")
        for component in components:
            if not isinstance(component, dict):
                raise DocumentCodecError(f"entity {entity_id!r} has a non-object component")
            component_type = component.get("type", component.get("type_id"))
            if not isinstance(component_type, str) or not component_type.strip():
                raise DocumentCodecError(f"entity {entity_id!r} has a component without type")
    for entity_id, parent_id in parent_ids.items():
        if parent_id is not None and parent_id not in entity_ids:
            raise DocumentCodecError(f"entity {entity_id!r} has missing parent {parent_id!r}")
    state: dict[str, int] = {}
    for start in entity_ids:
        current: str | None = start
        trail: list[str] = []
        while current is not None and state.get(current, 0) == 0:
            state[current] = 1
            trail.append(current)
            current = parent_ids[current]
        if current is not None and state.get(current) == 1:
            raise DocumentCodecError("entity hierarchy contains a cycle")
        for entity_id in trail:
            state[entity_id] = 2


def _fill_scene(message: Any, data: dict[str, Any]) -> None:
    message.schema_version = int(data.get("schema_version", 1))
    message.document_kind = str(data.get("kind", "scene"))
    message.scene_id = str(data["scene_id"])
    message.name = str(data["name"])
    if data.get("camera") is not None:
        message.camera.CopyFrom(_object(data["camera"]))
    for entity in data.get("entities", []):
        _fill_entity(message.entities.add(), entity)


def _fill_level(message: Any, data: dict[str, Any]) -> None:
    _fill_scene(message.scene, data)
    message.scene.document_kind = "level"
    message.metadata.SetInParent()
    metadata = data.get("level_metadata", {})
    if metadata.get("display_name") is not None:
        message.metadata.display_name = str(metadata["display_name"])
    if metadata.get("world_bounds") is not None:
        message.metadata.world_bounds.extend(float(value) for value in metadata["world_bounds"])
    if metadata.get("spawn_entity_id") is not None:
        message.metadata.spawn_entity_id = str(metadata["spawn_entity_id"])
    if metadata.get("default_camera_id") is not None:
        message.metadata.default_camera_id = str(metadata["default_camera_id"])
    message.metadata.tags.extend(str(tag) for tag in metadata.get("tags", []))


def _fill_entity(message: Any, data: dict[str, Any]) -> None:
    message.entity_id = str(data["entity_id"])
    message.name = str(data["name"])
    message.enabled = bool(data.get("enabled", True))
    message.layer = int(data.get("layer", 0))
    if data.get("parent_id") is not None:
        message.parent_id = str(data["parent_id"])
    message.tags.extend(str(tag) for tag in data.get("tags", []))
    for component in data.get("components", []):
        target = message.components.add()
        target.type_id = str(component.get("type", component.get("type_id", "")))
        target.enabled = bool(component.get("enabled", True))
        payload = component.get("payload")
        target.payload_explicit = payload is not None
        if payload is None:
            payload = {
                key: value
                for key, value in component.items()
                if key not in {"type", "type_id", "enabled"}
            }
        target.payload.CopyFrom(_object(payload))


def _scene_to_dict(
    message: Any, *, expected_kind: DocumentKind = DocumentKind.SCENE
) -> dict[str, Any]:
    if message.document_kind != expected_kind.value:
        raise DocumentCodecError(
            f"{expected_kind.value.title()}Document declares incompatible kind "
            f"{message.document_kind!r}"
        )
    data: dict[str, Any] = {
        "kind": expected_kind.value,
        "scene_id": message.scene_id,
        "name": message.name,
        "entities": [_entity_to_dict(entity) for entity in message.entities],
    }
    if message.schema_version != 1:
        data["schema_version"] = message.schema_version
    if message.HasField("camera"):
        data["camera"] = _object_to_dict(message.camera)
    return data


def _level_to_dict(message: Any) -> dict[str, Any]:
    data = _scene_to_dict(message.scene, expected_kind=DocumentKind.LEVEL)
    metadata: dict[str, Any] = {}
    if message.metadata.HasField("display_name"):
        metadata["display_name"] = message.metadata.display_name
    if message.metadata.world_bounds:
        metadata["world_bounds"] = list(message.metadata.world_bounds)
    if message.metadata.HasField("spawn_entity_id"):
        metadata["spawn_entity_id"] = message.metadata.spawn_entity_id
    if message.metadata.HasField("default_camera_id"):
        metadata["default_camera_id"] = message.metadata.default_camera_id
    if message.metadata.tags:
        metadata["tags"] = list(message.metadata.tags)
    data["level_metadata"] = metadata
    return data


def _entity_to_dict(message: Any) -> dict[str, Any]:
    return {
        "entity_id": message.entity_id,
        "name": message.name,
        "enabled": message.enabled,
        "layer": message.layer,
        "parent_id": message.parent_id if message.HasField("parent_id") else None,
        "tags": list(message.tags),
        "components": [_component_to_dict(component) for component in message.components],
    }


def _component_to_dict(message: Any) -> dict[str, Any]:
    payload = _object_to_dict(message.payload)
    if message.payload_explicit:
        return {"type": message.type_id, "enabled": message.enabled, "payload": payload}
    return {"type": message.type_id, "enabled": message.enabled, **payload}


def _object(values: dict[str, Any]) -> Any:
    result = common_pb2.JsonObject()  # type: ignore[attr-defined]
    for key, value in values.items():
        result.values[str(key)].CopyFrom(_value(value))
    return result


def _value(value: Any) -> Any:
    result = common_pb2.JsonValue()  # type: ignore[attr-defined]
    if value is None:
        result.null_value = True
    elif isinstance(value, bool):
        result.bool_value = value
    elif isinstance(value, int) and not isinstance(value, bool):
        result.int_value = value
    elif isinstance(value, float):
        result.float_value = value
    elif isinstance(value, str):
        result.string_value = value
    elif isinstance(value, dict):
        result.object_value.CopyFrom(_object(value))
    elif isinstance(value, list):
        result.array_value.values.extend(_value(item) for item in value)
    else:
        raise TypeError(f"unsupported JSON value: {type(value).__name__}")
    return result


def _object_to_dict(message: Any) -> dict[str, Any]:
    return {key: _value_to_python(value) for key, value in message.values.items()}


def _value_to_python(value: Any) -> Any:
    kind = value.WhichOneof("kind")
    if kind == "null_value":
        return None
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "float_value":
        return value.float_value
    if kind == "string_value":
        return value.string_value
    if kind == "object_value":
        return _object_to_dict(value.object_value)
    if kind == "array_value":
        return [_value_to_python(item) for item in value.array_value.values]
    raise ValueError("protobuf JSON value is empty")
