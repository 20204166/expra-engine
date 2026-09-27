"""Runtime Level preparation: isolated materialization and async load plumbing."""

from __future__ import annotations

import copy
import hashlib
import queue
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor
from expra_engine.runtime.level_anchor import WorldPersistentActorComponent

__all__ = (
    "_LoadCompletion",
    "_PreparedWorldLevel",
    "_deliver_level_result",
    "_materialize_world_level",
    "_session_owned_entity_ids",
    "_set_root_world_position",
    "_world_session_store_path",
)


@dataclass(frozen=True, slots=True)
class _PreparedWorldLevel:
    authored: Level
    runtime: Level


@dataclass(frozen=True, slots=True)
class _LoadCompletion:
    level_id: str
    generation: int
    prepared: _PreparedWorldLevel | None
    error: Exception | None


def _deliver_level_result(
    target: queue.SimpleQueue[_LoadCompletion],
    level_id: str,
    generation: int,
    future: Future[_PreparedWorldLevel],
) -> None:
    try:
        completion = _LoadCompletion(level_id, generation, future.result(), None)
    except Exception as error:  # noqa: BLE001 - deliver arbitrary loader failure on owner thread
        completion = _LoadCompletion(level_id, generation, None, error)
    target.put(completion)


def _set_root_world_position(entity: Entity, position: tuple[float, float]) -> None:
    if entity.parent_id is not None:
        raise ValueError("only a World-owned root actor can be held at a streaming boundary")
    transform = entity.get_component(TransformComponent)
    if transform is None:
        transform = TransformComponent()
        entity.add_component(transform)
    transform.x, transform.y = position


def _session_owned_entity_ids(level: Level | None) -> tuple[str, ...]:
    if level is None:
        return ()
    persistent_ids: set[str] = set()
    for entity in level.entities:
        if entity.get_component(WorldPersistentActorComponent) is not None:
            persistent_ids.update(
                item.entity_id for item in level.walk_hierarchy(entity.entity_id)
            )
    return tuple(
        sorted(entity.entity_id for entity in level.entities if entity.entity_id not in persistent_ids)
    )


def _world_session_store_path(world_id: str, slot: str) -> str:
    if (
        not isinstance(slot, str)
        or not slot
        or slot in {".", ".."}
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in slot)
    ):
        raise ValueError("World save slot must use letters, numbers, dot, underscore, or hyphen")
    digest = hashlib.sha256(world_id.encode("utf-8")).hexdigest()
    return f"world-sessions/{digest}/{slot}.json"


def _materialize_world_level(
    authored: Level,
    descriptor: LevelDescriptor,
    *,
    world_id: str,
) -> Level:
    """Create an isolated, namespaced runtime Level with a world-origin root."""
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"expra-world:{world_id}:{descriptor.instance_id}")
    root_id = str(uuid.uuid5(namespace, "level-root"))
    persistent_namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"expra-world-persistent:{world_id}")
    persistent_owner: dict[str, str] = {}
    for entity in authored.entities:
        marker = entity.get_component(WorldPersistentActorComponent)
        if marker is None:
            continue
        if entity.parent_id is not None:
            raise ValueError("World-persistent actor marker must be placed on a Level root Entity")
        if any(owner == marker.persistent_id for owner in persistent_owner.values()):
            raise ValueError(f"duplicate persistent actor ID: {marker.persistent_id!r}")
        for member in authored.walk_hierarchy(entity.entity_id):
            persistent_owner[member.entity_id] = marker.persistent_id
    id_map = {
        entity.entity_id: str(
            uuid.uuid5(
                persistent_namespace,
                f"{persistent_owner[entity.entity_id]}:{entity.entity_id}",
            )
            if entity.entity_id in persistent_owner
            else uuid.uuid5(namespace, f"entity:{entity.entity_id}")
        )
        for entity in authored.entities
    }
    data = authored.to_dict()
    data["scene_id"] = str(uuid.uuid5(namespace, f"scene:{authored.scene_id}"))
    camera = copy.deepcopy(data.get("camera", {}))
    if isinstance(camera, dict) and camera.get("target_entity_id") in id_map:
        camera["target_entity_id"] = id_map[camera["target_entity_id"]]
    data["camera"] = camera
    metadata = data.get("level_metadata", {})
    for key in ("spawn_entity_id", "default_camera_id"):
        if metadata.get(key) in id_map:
            metadata[key] = id_map[metadata[key]]
    runtime_entities: list[dict[str, Any]] = []
    for entity in data.get("entities", []):
        old_id = entity["entity_id"]
        parent_id = entity.get("parent_id")
        entity["entity_id"] = id_map[old_id]
        entity["parent_id"] = id_map[parent_id] if parent_id is not None else root_id
        runtime_entities.append(entity)
    root = Entity(
        f"World Level {descriptor.instance_id}",
        entity_id=root_id,
    )
    root.add_tag("expra_world_level_root")
    root.add_component(TransformComponent(x=descriptor.origin[0], y=descriptor.origin[1]))
    data["entities"] = [root.to_dict(), *runtime_entities]
    return Level.from_dict(data)
