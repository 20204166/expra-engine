"""Canonical lightweight World metadata and Level-connection graph."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any, ClassVar

from expra_engine.core.document_kind import DocumentKind


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip() or "\x00" in value:
        raise ValueError(f"{field_name} is invalid")
    return value


def _finite_tuple(value: object, count: int, field_name: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must contain {count} finite numbers")
    try:
        raw = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{field_name} must contain {count} finite numbers") from error
    if len(raw) != count or any(isinstance(item, bool) for item in raw):
        raise ValueError(f"{field_name} must contain {count} finite numbers")
    values = tuple(float(item) for item in raw)
    if not all(math.isfinite(item) for item in values):
        raise ValueError(f"{field_name} must contain {count} finite numbers")
    return values


def _relative_level_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Level resource_path must be a safe project-relative path")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in path.parts
        or not value.casefold().endswith(".level.pb")
    ):
        raise ValueError("Level resource_path must be a safe .level.pb project path")
    return value


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


class TransitionMode(StrEnum):
    SEAMLESS = "seamless"
    FADE = "fade"
    INSTANT = "instant"
    LOADING = "loading"


@dataclass(frozen=True, slots=True)
class LevelDescriptor:
    instance_id: str
    resource_path: str
    origin: tuple[float, float] = (0.0, 0.0)
    bounds: tuple[float, float, float, float] | None = None
    tags: tuple[str, ...] = ()
    always_loaded: bool = False
    priority: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.instance_id, "Level instance_id")
        _relative_level_path(self.resource_path)
        object.__setattr__(self, "origin", _finite_tuple(self.origin, 2, "Level origin"))
        if self.bounds is not None:
            bounds = _finite_tuple(self.bounds, 4, "Level bounds")
            if bounds[2] <= 0.0 or bounds[3] <= 0.0:
                raise ValueError("Level bounds width and height must be positive")
            object.__setattr__(self, "bounds", bounds)
        tags = tuple(_identifier(tag, "Level tag") for tag in self.tags)
        if len(set(tags)) != len(tags):
            raise ValueError("Level tags must be unique")
        object.__setattr__(self, "tags", tags)
        if type(self.always_loaded) is not bool or type(self.priority) is not int:
            raise ValueError("Level always_loaded and priority have invalid types")
        if not isinstance(self.metadata, dict):
            raise ValueError("Level metadata must be an object")
        try:
            json.dumps(self.metadata, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("Level metadata must contain finite JSON values") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "resource_path": self.resource_path,
            "origin": list(self.origin),
            "bounds": list(self.bounds) if self.bounds is not None else None,
            "tags": list(self.tags),
            "always_loaded": self.always_loaded,
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LevelDescriptor:
        return cls(
            instance_id=data.get("instance_id"),
            resource_path=data.get("resource_path"),
            origin=data.get("origin", (0.0, 0.0)),
            bounds=data.get("bounds"),
            tags=data.get("tags", ()),
            always_loaded=data.get("always_loaded", False),
            priority=data.get("priority", 0),
            metadata=_object(data.get("metadata", {}), "Level metadata"),
        )


@dataclass(frozen=True, slots=True)
class WorldConnection:
    connection_id: str
    source_level_id: str
    source_anchor_id: str
    destination_level_id: str
    destination_anchor_id: str
    bidirectional: bool = False
    transition: TransitionMode = TransitionMode.SEAMLESS
    preload_distance: float = 24.0
    unload_distance: float = 48.0

    def __post_init__(self) -> None:
        for name in (
            "connection_id",
            "source_level_id",
            "source_anchor_id",
            "destination_level_id",
            "destination_anchor_id",
        ):
            _identifier(getattr(self, name), name)
        if type(self.bidirectional) is not bool:
            raise ValueError("connection bidirectional must be a boolean")
        try:
            transition = TransitionMode(self.transition)
        except (TypeError, ValueError) as error:
            raise ValueError("connection transition mode is invalid") from error
        object.__setattr__(self, "transition", transition)
        preload = _finite_tuple((self.preload_distance,), 1, "preload_distance")[0]
        unload = _finite_tuple((self.unload_distance,), 1, "unload_distance")[0]
        if preload < 0.0 or unload <= preload:
            raise ValueError("unload_distance must be greater than non-negative preload_distance")
        object.__setattr__(self, "preload_distance", preload)
        object.__setattr__(self, "unload_distance", unload)

    def reversed(self) -> WorldConnection:
        """Build a separate directed reverse route for an authoring convenience."""
        return replace(
            self,
            connection_id=f"{self.connection_id}:reverse",
            source_level_id=self.destination_level_id,
            source_anchor_id=self.destination_anchor_id,
            destination_level_id=self.source_level_id,
            destination_anchor_id=self.source_anchor_id,
            bidirectional=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "source_level_id": self.source_level_id,
            "source_anchor_id": self.source_anchor_id,
            "destination_level_id": self.destination_level_id,
            "destination_anchor_id": self.destination_anchor_id,
            "bidirectional": self.bidirectional,
            "transition": self.transition.value,
            "preload_distance": self.preload_distance,
            "unload_distance": self.unload_distance,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldConnection:
        return cls(
            connection_id=data.get("connection_id"),
            source_level_id=data.get("source_level_id"),
            source_anchor_id=data.get("source_anchor_id"),
            destination_level_id=data.get("destination_level_id"),
            destination_anchor_id=data.get("destination_anchor_id"),
            bidirectional=data.get("bidirectional", False),
            transition=data.get("transition", TransitionMode.SEAMLESS),
            preload_distance=data.get("preload_distance", 24.0),
            unload_distance=data.get("unload_distance", 48.0),
        )


@dataclass(frozen=True, slots=True)
class WorldStreamingSettings:
    max_concurrent_loads: int = 2
    max_loaded_levels: int = 8

    def __post_init__(self) -> None:
        if (
            type(self.max_concurrent_loads) is not int
            or type(self.max_loaded_levels) is not int
            or self.max_concurrent_loads <= 0
            or self.max_loaded_levels <= 0
        ):
            raise ValueError("World streaming budgets must be positive integers")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_concurrent_loads": self.max_concurrent_loads,
            "max_loaded_levels": self.max_loaded_levels,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldStreamingSettings:
        return cls(
            max_concurrent_loads=data.get("max_concurrent_loads", 2),
            max_loaded_levels=data.get("max_loaded_levels", 8),
        )


@dataclass(frozen=True, slots=True)
class World:
    document_kind: ClassVar[DocumentKind] = DocumentKind.WORLD

    name: str
    world_id: str
    levels: tuple[LevelDescriptor, ...] = ()
    connections: tuple[WorldConnection, ...] = ()
    primary_anchor_id: str | None = None
    initial_level_id: str | None = None
    initial_entrance_id: str | None = None
    streaming: WorldStreamingSettings = field(default_factory=WorldStreamingSettings)
    metadata: dict[str, object] = field(default_factory=dict)
    _outgoing: dict[str, tuple[WorldConnection, ...]] = field(
        init=False, repr=False, compare=False
    )
    _incoming: dict[str, tuple[WorldConnection, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _identifier(self.name, "World name")
        _identifier(self.world_id, "World world_id")
        levels = tuple(self.levels)
        authored_connections = tuple(self.connections)
        if not all(isinstance(item, LevelDescriptor) for item in levels):
            raise ValueError("World levels must contain LevelDescriptor values")
        if not all(isinstance(item, WorldConnection) for item in authored_connections):
            raise ValueError("World connections must contain WorldConnection values")
        connections: list[WorldConnection] = []
        for connection in authored_connections:
            if connection.bidirectional:
                forward = replace(connection, bidirectional=False)
                connections.extend((forward, connection.reversed()))
            else:
                connections.append(connection)
        connections = tuple(connections)
        level_ids = [item.instance_id for item in levels]
        if len(set(level_ids)) != len(level_ids):
            raise ValueError("World Level instance IDs must be unique")
        connection_ids = [item.connection_id for item in connections]
        if len(set(connection_ids)) != len(connection_ids):
            raise ValueError("World connection IDs must be unique")
        known_levels = set(level_ids)
        for connection in connections:
            if (
                connection.source_level_id not in known_levels
                or connection.destination_level_id not in known_levels
            ):
                raise ValueError(
                    f"connection {connection.connection_id!r} references a missing Level instance"
                )
        if levels:
            if self.initial_level_id is None or self.initial_level_id not in known_levels:
                raise ValueError("World initial Level must reference a registered Level instance")
        elif self.initial_level_id is not None:
            raise ValueError("empty World cannot select an initial Level")
        if self.initial_entrance_id is not None:
            _identifier(self.initial_entrance_id, "World initial_entrance_id")
        if self.primary_anchor_id is not None:
            _identifier(self.primary_anchor_id, "World primary_anchor_id")
        if not isinstance(self.streaming, WorldStreamingSettings):
            raise ValueError("World streaming must be WorldStreamingSettings")
        startup_resident = {item.instance_id for item in levels if item.always_loaded}
        if self.initial_level_id is not None:
            startup_resident.add(self.initial_level_id)
        if len(startup_resident) > self.streaming.max_loaded_levels:
            raise ValueError("initial and always-loaded Levels exceed max_loaded_levels")
        if not isinstance(self.metadata, dict):
            raise ValueError("World metadata must be an object")
        try:
            json.dumps(self.metadata, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("World metadata must contain finite JSON values") from error
        outgoing: dict[str, list[WorldConnection]] = {}
        incoming: dict[str, list[WorldConnection]] = {}
        for connection in connections:
            outgoing.setdefault(connection.source_level_id, []).append(connection)
            incoming.setdefault(connection.destination_level_id, []).append(connection)
        object.__setattr__(self, "levels", levels)
        object.__setattr__(self, "connections", connections)
        object.__setattr__(
            self,
            "_outgoing",
            {key: tuple(sorted(value, key=lambda item: item.connection_id)) for key, value in outgoing.items()},
        )
        object.__setattr__(
            self,
            "_incoming",
            {key: tuple(sorted(value, key=lambda item: item.connection_id)) for key, value in incoming.items()},
        )

    def connections_from(
        self, level_id: str, *, include_reverse: bool = False
    ) -> tuple[WorldConnection, ...]:
        del include_reverse  # Compatibility flag; reverse routes are authored graph edges now.
        return self._outgoing.get(level_id, ())

    def connections_to(self, level_id: str) -> tuple[WorldConnection, ...]:
        return self._incoming.get(level_id, ())

    def connection_for_exit(
        self, level_id: str, anchor_id: str
    ) -> WorldConnection | None:
        return next(
            (
                connection
                for connection in self.connections_from(level_id, include_reverse=True)
                if connection.source_anchor_id == anchor_id
            ),
            None,
        )

    def neighbors(self, level_id: str) -> tuple[LevelDescriptor, ...]:
        by_id = {item.instance_id: item for item in self.levels}
        neighbor_ids = {
            connection.destination_level_id
            for connection in self.connections_from(level_id, include_reverse=True)
        }
        return tuple(by_id[key] for key in sorted(neighbor_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": DocumentKind.WORLD.value,
            "schema_version": 1,
            "world_id": self.world_id,
            "name": self.name,
            "levels": [item.to_dict() for item in self.levels],
            "connections": [item.to_dict() for item in self.connections],
            "primary_anchor_id": self.primary_anchor_id,
            "initial_level_id": self.initial_level_id,
            "initial_entrance_id": self.initial_entrance_id,
            "streaming": self.streaming.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> World:
        if data.get("kind", DocumentKind.WORLD.value) != DocumentKind.WORLD.value:
            raise ValueError("World document kind must be 'world'")
        version = data.get("schema_version", 1)
        if type(version) is not int or version != 1:
            raise ValueError("unsupported World schema version")
        raw_levels = data.get("levels", ())
        raw_connections = data.get("connections", ())
        if not isinstance(raw_levels, (tuple, list)):
            raise ValueError("World levels must be a sequence")
        if not isinstance(raw_connections, (tuple, list)):
            raise ValueError("World connections must be a sequence")
        raw_streaming = _object(data.get("streaming", {}), "World streaming")
        return cls(
            name=data.get("name"),
            world_id=data.get("world_id"),
            levels=tuple(LevelDescriptor.from_dict(_object(item, "Level descriptor")) for item in raw_levels),
            connections=tuple(
                WorldConnection.from_dict(_object(item, "World connection"))
                for item in raw_connections
            ),
            primary_anchor_id=data.get("primary_anchor_id"),
            initial_level_id=data.get("initial_level_id"),
            initial_entrance_id=data.get("initial_entrance_id"),
            streaming=WorldStreamingSettings.from_dict(raw_streaming),
            metadata=_object(data.get("metadata", {}), "World metadata"),
        )
