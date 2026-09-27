"""Pure World desired-residency policy and generation-fenced state records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from expra_engine.core.scene import Level
from expra_engine.core.world import World, WorldConnection

if TYPE_CHECKING:
    from expra_engine.runtime.world_transition import WorldTransitionSnapshot

__all__ = (
    "LevelResidencyManager",
    "LevelResidencySnapshot",
    "LevelResidencyState",
    "PendingWorldTransition",
    "ResidencyCapacityError",
    "StreamingAnchor",
    "StreamingDecision",
    "WorldCameraContext",
    "WorldStreamingPolicy",
    "WorldStreamingSnapshot",
)


class LevelResidencyState(StrEnum):
    UNLOADED = "unloaded"
    QUEUED = "queued"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    DORMANT = "dormant"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResidencyCapacityError(ValueError):
    """Raised when a request would exceed the configured resident-Level bound."""


@dataclass(frozen=True, slots=True)
class StreamingAnchor:
    """A generic actor/camera/editor location used to choose Level residency."""

    anchor_id: str
    level_id: str
    position: tuple[float, float]
    entity_id: str | None = None

    def __post_init__(self) -> None:
        if not self.anchor_id or not self.level_id:
            raise ValueError("streaming anchor IDs must be non-empty")
        if len(self.position) != 2 or any(
            isinstance(value, bool) or not math.isfinite(float(value))
            for value in self.position
        ):
            raise ValueError("streaming anchor position must contain two finite values")
        object.__setattr__(self, "position", (float(self.position[0]), float(self.position[1])))


@dataclass(frozen=True, slots=True)
class StreamingDecision:
    active_level_ids: tuple[str, ...]
    resident_level_ids: tuple[str, ...]
    preload_level_ids: tuple[str, ...]
    reasons: tuple[tuple[str, tuple[str, ...]], ...]


class WorldStreamingPolicy:
    """Deterministic connection-aware preload and hysteretic retention policy."""

    def decide(
        self,
        world: World,
        anchors: tuple[StreamingAnchor, ...] | list[StreamingAnchor],
        portal_positions: dict[tuple[str, str], tuple[float, float]],
        *,
        resident_level_ids: tuple[str, ...] | list[str] = (),
        pinned_level_ids: tuple[str, ...] | list[str] = (),
        initial_level_id: str | None = None,
    ) -> StreamingDecision:
        descriptors = {item.instance_id: item for item in world.levels}
        anchor_values = tuple(anchors)
        if any(not isinstance(item, StreamingAnchor) for item in anchor_values):
            raise TypeError("anchors must contain StreamingAnchor values")
        for anchor in anchor_values:
            if anchor.level_id not in descriptors:
                raise ValueError(f"streaming anchor references an unknown Level: {anchor.level_id!r}")
        pinned = set(pinned_level_ids)
        if pinned - descriptors.keys():
            raise ValueError("pinned Level set contains an unknown Level")
        active = {item.level_id for item in anchor_values}
        if not active and initial_level_id is not None:
            if initial_level_id not in descriptors:
                raise ValueError("initial Level is not registered in the World")
            active.add(initial_level_id)
        required = active | pinned | {
            item.instance_id for item in world.levels if item.always_loaded
        }
        if len(required) > world.streaming.max_loaded_levels:
            raise ResidencyCapacityError("required active/pinned Levels exceed max_loaded_levels")

        reasons: dict[str, set[str]] = {level_id: {"anchor"} for level_id in active}
        for level_id in pinned:
            reasons.setdefault(level_id, set()).add("pinned")
        for item in world.levels:
            if item.always_loaded:
                reasons.setdefault(item.instance_id, set()).add("always_loaded")

        candidates: dict[str, tuple[float, int]] = {}
        preload_ids: set[str] = set()
        resident = set(resident_level_ids)
        for anchor in anchor_values:
            for connection in world.connections_from(anchor.level_id, include_reverse=True):
                portal = portal_positions.get((connection.source_level_id, connection.source_anchor_id))
                if portal is None:
                    continue
                if len(portal) != 2 or not all(math.isfinite(float(value)) for value in portal):
                    raise ValueError("portal positions must contain two finite values")
                distance = math.dist(anchor.position, (float(portal[0]), float(portal[1])))
                destination = connection.destination_level_id
                if distance <= connection.preload_distance:
                    preload_ids.add(destination)
                    reasons.setdefault(destination, set()).add("connection_preload")
                    score = (distance, descriptors[destination].priority)
                elif destination in resident and distance <= connection.unload_distance:
                    reasons.setdefault(destination, set()).add("hysteresis")
                    score = (distance, descriptors[destination].priority)
                else:
                    continue
                previous = candidates.get(destination)
                if previous is None or score < previous:
                    candidates[destination] = score

        optional = sorted(
            (level_id for level_id in candidates if level_id not in required),
            key=lambda level_id: (
                candidates[level_id][0],
                -candidates[level_id][1],
                level_id,
            ),
        )
        room = world.streaming.max_loaded_levels - len(required)
        selected_optional = set(optional[:room])
        selected = required | selected_optional
        selected_preloads = preload_ids & selected
        return StreamingDecision(
            active_level_ids=tuple(sorted(active)),
            resident_level_ids=tuple(sorted(selected)),
            preload_level_ids=tuple(sorted(selected_preloads)),
            reasons=tuple(
                (level_id, tuple(sorted(reasons.get(level_id, ()))))
                for level_id in sorted(selected)
            ),
        )


@dataclass(frozen=True, slots=True)
class WorldCameraContext:
    """Inspectable camera ownership/context without owning camera motion state."""

    camera_id: str
    primary_level_id: str | None
    camera_context_level_id: str | None
    follow_target_entity_id: str | None
    active_level_ids: tuple[str, ...]
    effective_bounds: tuple[float, float, float, float] | None
    bounds_sources: tuple[str, ...]
    recenter_generation: int = 0


@dataclass(frozen=True, slots=True)
class PendingWorldTransition:
    anchor_id: str
    connection: WorldConnection
    blocking_position: tuple[float, float]
    persistent_id: str
    actor_entity_id: str
    manual: bool = False


@dataclass(frozen=True, slots=True)
class LevelResidencySnapshot:
    level_id: str
    state: LevelResidencyState
    generation: int
    has_level: bool
    level_name: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class WorldStreamingSnapshot:
    world_id: str
    levels: tuple[LevelResidencySnapshot, ...]
    pending_level_ids: tuple[str, ...]
    in_flight_level_ids: tuple[str, ...]
    stale_results_discarded: int
    max_concurrent_loads: int
    max_resident_levels: int
    primary_levels: tuple[tuple[str, str | None], ...] = ()
    residency_reasons: tuple[tuple[str, tuple[str, ...]], ...] = ()
    last_transition: tuple[str, str, str] | None = None
    last_transition_error: str | None = None
    connection_preloads: tuple[str, ...] = ()
    camera: WorldCameraContext | None = None
    pending_transitions: tuple[PendingWorldTransition, ...] = ()
    session_state_counts: tuple[tuple[str, int], ...] = ()
    last_session_error: str | None = None
    transition: WorldTransitionSnapshot | None = None


@dataclass(slots=True)
class _LevelResidency:
    state: LevelResidencyState = LevelResidencyState.UNLOADED
    generation: int = 0
    has_level: bool = False
    level_name: str | None = None
    error: str | None = None


class LevelResidencyManager:
    """Explicit generation-fenced lifecycle for a finite World descriptor set."""

    def __init__(self, level_ids: tuple[str, ...] | list[str], *, max_resident_levels: int = 8) -> None:
        if type(max_resident_levels) is not int or max_resident_levels <= 0:
            raise ValueError("max_resident_levels must be a positive integer")
        identifiers = tuple(level_ids)
        if any(not isinstance(value, str) or not value.strip() for value in identifiers):
            raise ValueError("Level IDs must be non-empty strings")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Level IDs must be unique")
        self.max_resident_levels = max_resident_levels
        self._records = {value: _LevelResidency() for value in identifiers}

    def state(self, level_id: str) -> LevelResidencySnapshot:
        record = self._record(level_id)
        return LevelResidencySnapshot(
            level_id,
            record.state,
            record.generation,
            record.has_level,
            record.level_name,
            record.error,
        )

    def request_load(self, level_id: str) -> int:
        record = self._record(level_id)
        if record.state in {
            LevelResidencyState.QUEUED,
            LevelResidencyState.LOADING,
            LevelResidencyState.LOADED,
            LevelResidencyState.ACTIVE,
            LevelResidencyState.DORMANT,
        }:
            return record.generation
        if self._resident_count() >= self.max_resident_levels:
            raise ResidencyCapacityError("World resident-Level budget is full")
        record.generation += 1
        record.state = LevelResidencyState.QUEUED
        record.has_level = False
        record.level_name = None
        record.error = None
        return record.generation

    def begin_load(self, level_id: str, generation: int) -> bool:
        record = self._record(level_id)
        if record.generation != generation or record.state is not LevelResidencyState.QUEUED:
            return False
        record.state = LevelResidencyState.LOADING
        return True

    def complete_load(self, level_id: str, generation: int, level: Level) -> bool:
        record = self._record(level_id)
        if record.generation != generation or record.state is not LevelResidencyState.LOADING:
            return False
        if not isinstance(level, Level):
            raise TypeError("World Level loader must return a Level")
        level.validate_anchors()
        record.has_level = True
        record.level_name = level.name
        record.error = None
        record.state = LevelResidencyState.LOADED
        return True

    def fail_load(self, level_id: str, generation: int, error: Exception) -> bool:
        record = self._record(level_id)
        if record.generation != generation or record.state is not LevelResidencyState.LOADING:
            return False
        record.has_level = False
        record.level_name = None
        record.error = f"{type(error).__name__}: {error}"[:200]
        record.state = LevelResidencyState.FAILED
        return True

    def fail_activation(self, level_id: str, error: Exception) -> bool:
        record = self._record(level_id)
        if record.state not in {
            LevelResidencyState.LOADED,
            LevelResidencyState.DORMANT,
            LevelResidencyState.ACTIVE,
        }:
            return False
        record.generation += 1
        record.has_level = False
        record.level_name = None
        record.error = f"{type(error).__name__}: {error}"[:200]
        record.state = LevelResidencyState.FAILED
        return True

    def cancel_load(self, level_id: str) -> bool:
        record = self._record(level_id)
        if record.state not in {LevelResidencyState.QUEUED, LevelResidencyState.LOADING}:
            return False
        record.generation += 1
        record.state = LevelResidencyState.CANCELLED
        record.has_level = False
        record.level_name = None
        record.error = None
        return True

    def activate(self, level_id: str) -> bool:
        record = self._record(level_id)
        if record.state not in {LevelResidencyState.LOADED, LevelResidencyState.DORMANT}:
            return False
        record.state = LevelResidencyState.ACTIVE
        return True

    def deactivate(self, level_id: str) -> bool:
        record = self._record(level_id)
        if record.state is not LevelResidencyState.ACTIVE:
            return False
        record.state = LevelResidencyState.DORMANT
        return True

    def unload(self, level_id: str) -> bool:
        record = self._record(level_id)
        if record.state not in {
            LevelResidencyState.LOADED,
            LevelResidencyState.DORMANT,
            LevelResidencyState.FAILED,
            LevelResidencyState.CANCELLED,
        }:
            return False
        record.generation += 1
        record.state = LevelResidencyState.UNLOADED
        record.has_level = False
        record.level_name = None
        record.error = None
        return True

    def snapshots(self) -> tuple[LevelResidencySnapshot, ...]:
        return tuple(self.state(level_id) for level_id in sorted(self._records))

    def _resident_count(self) -> int:
        return sum(
            record.state
            in {
                LevelResidencyState.QUEUED,
                LevelResidencyState.LOADING,
                LevelResidencyState.LOADED,
                LevelResidencyState.ACTIVE,
                LevelResidencyState.DORMANT,
            }
            for record in self._records.values()
        )

    def _record(self, level_id: str) -> _LevelResidency:
        try:
            return self._records[level_id]
        except KeyError as error:
            raise KeyError(f"unknown World Level instance: {level_id!r}") from error
