"""Explicitly authored opt-in state that World runtime captures across unload."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from expra_engine.core.component import Component, TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level
from expra_engine.runtime.level_anchor import WorldPersistentActorComponent
from expra_engine.runtime.world_policy import LevelResidencyState

if TYPE_CHECKING:
    from expra_engine.filesystem.user_data import UserDataStore

__all__ = (
    "WorldSessionPersistenceMixin",
    "WorldSessionState",
    "WorldSessionStateComponent",
    "WorldSessionStateError",
)


class WorldSessionStateError(ValueError):
    """Session state cannot be safely captured or restored for one Level."""


@dataclass(slots=True)
class WorldSessionState:
    """Versioned, in-memory opt-in deltas; disk save remains an explicit caller action."""

    world_id: str
    schema_version: int = 1
    levels: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    deleted_entities: dict[str, set[str]] = field(default_factory=dict)
    persistent_actors: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_levels: dict[str, str] = field(default_factory=dict)
    world_resource: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.world_id, str) or not self.world_id.strip():
            raise ValueError("World session requires a World ID")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported World session schema version")
        if self.world_resource is not None and (
            not isinstance(self.world_resource, str) or not self.world_resource.strip()
        ):
            raise ValueError("World session resource identity must be a non-empty string")

    def capture_level(
        self,
        level_id: str,
        level: Level,
        *,
        authored_entity_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.capture_entities(
            level_id,
            level.entities,
            authored_entity_ids=authored_entity_ids,
        )

    def capture_entities(
        self,
        level_id: str,
        entities: tuple[Entity, ...],
        *,
        authored_entity_ids: tuple[str, ...] | None = None,
    ) -> None:
        staged: dict[str, dict[str, Any]] = {}
        entity_ids = {entity.entity_id for entity in entities}
        authored_ids = set(authored_entity_ids) if authored_entity_ids is not None else None
        for entity in entities:
            if authored_ids is not None and entity.entity_id not in authored_ids:
                continue
            if entity.get_component(WorldPersistentActorComponent) is not None:
                continue
            component = entity.get_component(WorldSessionStateComponent)
            if component is None:
                continue
            try:
                component.validate()
                staged[entity.entity_id] = deepcopy(component.values)
            except Exception as error:
                raise WorldSessionStateError(
                    f"could not capture session values for Entity {entity.entity_id!r} "
                    f"in Level {level_id!r}: {type(error).__name__}"
                ) from error
        if staged:
            self.levels[level_id] = staged
        else:
            self.levels.pop(level_id, None)
        if authored_entity_ids is not None:
            deleted = authored_ids - entity_ids
            if deleted:
                self.deleted_entities[level_id] = deleted
            else:
                self.deleted_entities.pop(level_id, None)

    def capture_persistent_actor(
        self,
        persistent_id: str,
        source_level_id: str,
        entities: tuple[Entity, ...],
        *,
        current_level_id: str | None = None,
    ) -> None:
        actor_entities: dict[str, dict[str, Any]] = {}
        for entity in entities:
            transform = entity.get_component(TransformComponent)
            session = entity.get_component(WorldSessionStateComponent)
            if session is not None:
                session.validate()
            actor_entities[entity.entity_id] = {
                "transform": (
                    [
                        transform.x,
                        transform.y,
                        transform.rotation,
                        transform.scale_x,
                        transform.scale_y,
                    ]
                    if transform is not None
                    else None
                ),
                "state": deepcopy(session.values) if session is not None else None,
            }
        self.persistent_actors[persistent_id] = {
            "source_level_id": source_level_id,
            "current_level_id": current_level_id or source_level_id,
            "entities": actor_entities,
        }

    def restore_persistent_actor(
        self,
        persistent_id: str,
        entities: tuple[Entity, ...],
    ) -> tuple[str, str] | None:
        snapshot = self.persistent_actors.get(persistent_id)
        if snapshot is None:
            return None
        source_level_id = snapshot.get("source_level_id")
        current_level_id = snapshot.get("current_level_id", source_level_id)
        stored_entities = snapshot.get("entities")
        if (
            not isinstance(source_level_id, str)
            or not isinstance(current_level_id, str)
            or not isinstance(stored_entities, dict)
        ):
            raise WorldSessionStateError("stored persistent actor snapshot is malformed")
        current = {entity.entity_id: entity for entity in entities}
        staged: list[tuple[TransformComponent | None, tuple[float, ...] | None, WorldSessionStateComponent | None, dict[str, Any] | None]] = []
        for entity_id, values in stored_entities.items():
            entity = current.get(entity_id)
            if entity is None or not isinstance(values, dict):
                raise WorldSessionStateError(
                    f"persistent actor Entity is missing: {entity_id!r}"
                )
            raw_transform = values.get("transform")
            transform_values: tuple[float, ...] | None = None
            transform = entity.get_component(TransformComponent)
            if raw_transform is not None:
                transform_values = _finite_transform(raw_transform)
                if transform is None:
                    raise WorldSessionStateError(
                        f"persistent actor Transform is missing: {entity_id!r}"
                    )
            raw_state = values.get("state")
            session = entity.get_component(WorldSessionStateComponent)
            if raw_state is not None:
                if session is None or not isinstance(raw_state, dict):
                    raise WorldSessionStateError(
                        f"persistent actor state component is missing: {entity_id!r}"
                    )
                _validate_json_value(raw_state, "persistent actor state")
            staged.append((transform, transform_values, session, raw_state))
        for transform, transform_values, session, raw_state in staged:
            if transform is not None and transform_values is not None:
                (
                    transform.x,
                    transform.y,
                    transform.rotation,
                    transform.scale_x,
                    transform.scale_y,
                ) = transform_values
            if session is not None and raw_state is not None:
                session.values = deepcopy(raw_state)
        return source_level_id, current_level_id

    def restore_level(self, level_id: str, level: Level) -> None:
        delta = self.levels.get(level_id)
        deleted_entity_ids = self.deleted_entities.get(level_id, set())
        if not delta and not deleted_entity_ids:
            return
        delta = delta or {}
        staged: list[tuple[WorldSessionStateComponent, dict[str, Any]]] = []
        for entity_id, values in delta.items():
            if entity_id in deleted_entity_ids:
                continue
            entity = level.find_entity(entity_id)
            component = (
                entity.get_component(WorldSessionStateComponent) if entity is not None else None
            )
            if component is None:
                raise WorldSessionStateError(
                    f"session state Entity/component is missing: {entity_id!r} in {level_id!r}"
                )
            try:
                json.dumps(values, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise WorldSessionStateError("stored session values are malformed") from error
            staged.append((component, deepcopy(values)))
        for component, values in staged:
            component.values = values
        for entity_id in sorted(deleted_entity_ids):
            if level.find_entity(entity_id) is not None:
                level.remove_entity(entity_id, recursive=True)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "levels": {
                level_id: {
                    entity_id: deepcopy(values[entity_id])
                    for entity_id in sorted(values)
                }
                for level_id, values in sorted(self.levels.items())
            },
            "deleted_entities": {
                level_id: sorted(entity_ids)
                for level_id, entity_ids in sorted(self.deleted_entities.items())
            },
            "persistent_actors": {
                persistent_id: deepcopy(values)
                for persistent_id, values in sorted(self.persistent_actors.items())
            },
            "current_levels": dict(sorted(self.current_levels.items())),
            "world_resource": self.world_resource,
        }
        try:
            json.dumps(result, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise WorldSessionStateError("World session contains non-JSON values") from error
        return result

    def to_json(self) -> str:
        """Return deterministic UTF-8-ready JSON for explicit save-game writes."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldSessionState:
        if not isinstance(data, Mapping):
            raise ValueError("World session must be an object")
        version = data.get("schema_version", 1)
        if type(version) is not int or version != 1:
            raise ValueError("unsupported World session schema version")
        world_id = data.get("world_id")
        if not isinstance(world_id, str) or not world_id.strip():
            raise ValueError("World session requires a World ID")
        resource = data.get("world_resource")
        if resource is not None and (not isinstance(resource, str) or not resource.strip()):
            raise ValueError("World session resource identity must be a non-empty string")
        levels = _nested_json_objects(data.get("levels", {}), "levels")
        raw_deleted = data.get("deleted_entities", {})
        if not isinstance(raw_deleted, Mapping):
            raise ValueError("World session deleted_entities must be an object")
        deleted: dict[str, set[str]] = {}
        for level_id, entity_ids in raw_deleted.items():
            if not isinstance(level_id, str) or not level_id:
                raise ValueError("World session Level IDs must be non-empty strings")
            if not isinstance(entity_ids, (list, tuple)) or any(
                not isinstance(entity_id, str) or not entity_id for entity_id in entity_ids
            ):
                raise ValueError("World session deleted entity IDs must be strings")
            if len(set(entity_ids)) != len(entity_ids):
                raise ValueError("World session deleted entity IDs must be unique")
            deleted[level_id] = set(entity_ids)
        actors = _nested_json_objects(data.get("persistent_actors", {}), "persistent_actors")
        raw_current = data.get("current_levels", {})
        if not isinstance(raw_current, Mapping) or any(
            not isinstance(anchor_id, str)
            or not anchor_id
            or not isinstance(level_id, str)
            or not level_id
            for anchor_id, level_id in raw_current.items()
        ):
            raise ValueError("World session current_levels must map IDs to Level IDs")
        return cls(
            world_id,
            schema_version=version,
            levels=levels,
            deleted_entities=deleted,
            persistent_actors=actors,
            current_levels=dict(raw_current),
            world_resource=resource,
        )


def _nested_json_objects(value: object, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise ValueError(f"World session {name} must be an object")
    result: dict[str, dict[str, Any]] = {}
    for outer_id, inner in value.items():
        if not isinstance(outer_id, str) or not outer_id or not isinstance(inner, Mapping):
            raise ValueError(f"World session {name} contains an invalid ID or object")
        item = dict(inner)
        try:
            json.dumps(item, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError(f"World session {name} contains non-JSON values") from error
        result[outer_id] = deepcopy(item)
    return result


def _validate_json_value(value: object, name: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise WorldSessionStateError(f"{name} must contain finite JSON values") from error


def _finite_transform(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 5 or any(
        isinstance(item, bool) for item in value
    ):
        raise WorldSessionStateError("stored persistent actor Transform is malformed")
    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError) as error:
        raise WorldSessionStateError("stored persistent actor Transform is malformed") from error
    if not all(math.isfinite(item) for item in values):
        raise WorldSessionStateError("stored persistent actor Transform must be finite")
    return values


class WorldSessionStateComponent(Component):
    """JSON-only mutable values captured for an Entity during World Level unload.

    The component is the explicit opt-in boundary. Other runtime component
    fields are not implicitly copied into the World session delta.
    """

    component_type = "world_session_state"

    def __init__(self, values: dict[str, Any] | None = None, *, enabled: bool = True) -> None:
        super().__init__(enabled=enabled)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if not isinstance(values or {}, dict):
            raise ValueError("World session values must be an object")
        self.values = deepcopy(values or {})
        self.validate()

    def validate(self) -> None:
        try:
            json.dumps(self.values, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("World session values must contain finite JSON values") from error

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "values": deepcopy(self.values),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldSessionStateComponent:
        return cls(data.get("values", {}), enabled=data.get("enabled", True))


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


class WorldSessionPersistenceMixin:
    """Save/load World session data through the canonical UserDataStore."""

    @property
    def session_state(self) -> dict[str, Any]:
        """Return a detached, versioned snapshot of in-memory Level deltas."""
        return self._session_state.to_dict()

    def save_session(self, store: UserDataStore, *, slot: str = "default") -> str:
        """Explicitly save a detached World session under UserDataStore's game root."""
        if self._closed:
            raise RuntimeError("World streaming system is closed")
        if self._started:
            self._assert_owner()
        path = _world_session_store_path(self.world.world_id, slot)
        candidate = WorldSessionState.from_dict(self._session_state.to_dict())
        candidate.world_resource = self.world_resource_path
        self._capture_live_session(candidate)
        store.write_text(path, candidate.to_json(), namespace="game")
        self._session_state = candidate
        return path

    def load_session(self, store: UserDataStore, *, slot: str = "default") -> None:
        """Load a save before Play; malformed or mismatched data is never published."""
        if self._closed:
            raise RuntimeError("World streaming system is closed")
        if self._started:
            raise RuntimeError("World session must be loaded before the World starts")
        path = _world_session_store_path(self.world.world_id, slot)
        raw = json.loads(store.read_text(path, namespace="game"))
        candidate = WorldSessionState.from_dict(raw)
        if candidate.world_id != self.world.world_id:
            raise WorldSessionStateError("save belongs to a different World")
        if (
            candidate.world_resource is not None
            and self.world_resource_path is not None
            and candidate.world_resource != self.world_resource_path
        ):
            raise WorldSessionStateError("save belongs to a different World resource")
        self._session_state = candidate

    def _capture_live_session(self, candidate: WorldSessionState) -> None:
        candidate.current_levels = {
            anchor.anchor_id: anchor.level_id
            for anchor in self.streaming_anchors()
        }
        for level_id in self.loaded_levels():
            authored_ids = self._authored_state_entity_ids.get(level_id)
            if self._residency.state(level_id).state is LevelResidencyState.ACTIVE:
                entities = tuple(
                    entity
                    for entity_id in self._runtime_entity_ids.get(level_id, ())
                    if (entity := self.runtime_scene.find_entity(entity_id)) is not None
                )
            else:
                runtime_level = self._runtime_levels.get(level_id)
                entities = runtime_level.entities if runtime_level is not None else ()
            candidate.capture_entities(
                level_id,
                tuple(entities),
                authored_entity_ids=authored_ids,
            )
        for persistent_id, entity_ids in self._persistent_actor_entity_ids.items():
            source_level_id = self._persistent_actor_source_levels.get(persistent_id)
            if source_level_id is None:
                continue
            entities = tuple(
                entity
                for entity_id in entity_ids
                if (entity := self.runtime_scene.find_entity(entity_id)) is not None
            )
            candidate.capture_persistent_actor(
                persistent_id,
                source_level_id,
                entities,
                current_level_id=self._persistent_actor_levels.get(persistent_id),
            )
