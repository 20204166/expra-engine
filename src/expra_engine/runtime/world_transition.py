"""One owner for explicit World travel presentation and handover phases."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level
from expra_engine.core.world import TransitionMode, WorldConnection
from expra_engine.runtime.level_anchor import LevelAnchorComponent, LevelAnchorKind
from expra_engine.runtime.world_geometry import (
    _inside_anchor_trigger,
    _segment_intersects_anchor_trigger,
)
from expra_engine.runtime.world_materialize import _set_root_world_position
from expra_engine.runtime.world_policy import (
    LevelResidencyState,
    PendingWorldTransition,
    ResidencyCapacityError,
    StreamingAnchor,
)

if TYPE_CHECKING:
    pass

__all__ = (
    "TransitionStatus",
    "WorldTransitionController",
    "WorldTransitionSnapshot",
    "WorldTraversalMixin",
)


class TransitionStatus(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    FADING_OUT = "fading_out"
    SWITCHING = "switching"
    FADING_IN = "fading_in"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorldTransitionSnapshot:
    connection_id: str | None = None
    source_level_id: str | None = None
    destination_level_id: str | None = None
    mode: TransitionMode | None = None
    status: TransitionStatus = TransitionStatus.IDLE
    alpha: float = 0.0
    error: str | None = None


class WorldTransitionController:
    """Coordinate preparation, optional fade presentation, and one safe commit."""

    def __init__(self, *, fade_duration: float = 0.2) -> None:
        if not math.isfinite(fade_duration) or fade_duration <= 0.0:
            raise ValueError("fade_duration must be positive and finite")
        self.fade_duration = float(fade_duration)
        self._connection_id: str | None = None
        self._source_level_id: str | None = None
        self._destination_level_id: str | None = None
        self._mode: TransitionMode | None = None
        self._status = TransitionStatus.IDLE
        self._elapsed = 0.0
        self._error: str | None = None
        self._switch_pending = False

    @property
    def status(self) -> TransitionStatus:
        return self._status

    @property
    def alpha(self) -> float:
        if self._status is TransitionStatus.SWITCHING and self._mode is TransitionMode.FADE:
            return 1.0
        if self._status is TransitionStatus.FADING_OUT:
            return min(1.0, self._elapsed / self.fade_duration)
        if self._status is TransitionStatus.FADING_IN:
            return max(0.0, 1.0 - self._elapsed / self.fade_duration)
        return 0.0

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def snapshot(self) -> WorldTransitionSnapshot:
        return WorldTransitionSnapshot(
            connection_id=self._connection_id,
            source_level_id=self._source_level_id,
            destination_level_id=self._destination_level_id,
            mode=self._mode,
            status=self._status,
            alpha=self.alpha,
            error=self._error,
        )

    def begin(
        self,
        connection_id: str,
        source_level_id: str,
        destination_level_id: str,
        mode: TransitionMode,
    ) -> None:
        if self._status in {
            TransitionStatus.PREPARING,
            TransitionStatus.FADING_OUT,
            TransitionStatus.SWITCHING,
            TransitionStatus.FADING_IN,
        }:
            raise RuntimeError("a World transition is already in progress")
        if not connection_id or not source_level_id or not destination_level_id:
            raise ValueError("World transition requires connection and Level IDs")
        self._connection_id = connection_id
        self._source_level_id = source_level_id
        self._destination_level_id = destination_level_id
        self._mode = TransitionMode(mode)
        self._status = TransitionStatus.PREPARING
        self._elapsed = 0.0
        self._error = None
        self._switch_pending = False

    def destination_ready(self) -> None:
        if self._status is not TransitionStatus.PREPARING:
            raise RuntimeError("World transition is not preparing a destination")
        if self._mode is TransitionMode.FADE:
            self._status = TransitionStatus.FADING_OUT
            self._elapsed = 0.0
        else:
            self._status = TransitionStatus.SWITCHING
            self._switch_pending = True

    def advance(self, dt: float) -> bool:
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("World transition dt must be finite and non-negative")
        if self._status is TransitionStatus.FADING_OUT:
            self._elapsed += dt
            if self._elapsed >= self.fade_duration:
                self._elapsed = self.fade_duration
                self._status = TransitionStatus.SWITCHING
                self._switch_pending = True
        elif self._status is TransitionStatus.FADING_IN:
            self._elapsed += dt
            if self._elapsed >= self.fade_duration:
                self._elapsed = self.fade_duration
                self._status = (
                    TransitionStatus.FAILED
                    if self._error is not None
                    else TransitionStatus.COMPLETE
                )
        return self._switch_pending

    def complete_switch(self) -> None:
        if self._status is not TransitionStatus.SWITCHING or not self._switch_pending:
            raise RuntimeError("World transition has no pending Level handover")
        self._switch_pending = False
        if self._mode is TransitionMode.FADE:
            self._status = TransitionStatus.FADING_IN
            self._elapsed = 0.0
        else:
            self._status = TransitionStatus.COMPLETE

    def fail(self, reason: str) -> None:
        if self._status in {TransitionStatus.IDLE, TransitionStatus.COMPLETE}:
            raise RuntimeError("no active World transition can fail")
        self._error = str(reason)[:240]
        self._switch_pending = False
        if self._mode is TransitionMode.FADE and self.alpha > 0.0:
            self._status = TransitionStatus.FADING_IN
            self._elapsed = 0.0
        else:
            self._status = TransitionStatus.FAILED
            self._elapsed = 0.0


class WorldTraversalMixin:
    """Connection-driven travel and transition handover, owned by WorldStreamingSystem.

    Split from ``world_streaming.py`` as the canonical travel/transition
    responsibility. It operates on the hosting system's residency, anchor,
    persistent-actor, and camera state; it introduces no parallel systems.
    """

    def travel(self, connection_id: str, *, anchor_id: str | None = None) -> bool:
        """Request authored connection travel through the shared residency path."""
        self._assert_owner()
        anchor_id = anchor_id or self.world.primary_anchor_id
        if anchor_id is None:
            raise ValueError("World travel requires a registered streaming anchor")
        anchor = next(
            (item for item in self.streaming_anchors() if item.anchor_id == anchor_id), None
        )
        if anchor is None or anchor.entity_id is None:
            raise ValueError(f"streaming anchor is unavailable: {anchor_id}")
        connection = next(
            (
                item
                for item in self.world.connections_from(anchor.level_id, include_reverse=True)
                if item.connection_id == connection_id
            ),
            None,
        )
        if connection is None:
            raise ValueError(f"connection is not reachable from Level {anchor.level_id!r}")
        actor = self.runtime_scene.find_entity(anchor.entity_id)
        persistent_id = self._persistent_id_for_entity(anchor.entity_id)
        if actor is None or persistent_id is None:
            raise ValueError("World travel requires an active World-persistent actor")
        source_key = (connection.source_level_id, connection.source_anchor_id)
        source_entity = self._active_anchor_entity(*source_key)
        source_marker = (
            source_entity.get_component(LevelAnchorComponent) if source_entity is not None else None
        )
        source_position = self.portal_positions().get(source_key)
        if source_entity is None or source_marker is None or source_position is None:
            raise ValueError("World travel source anchor is not active")
        if not self._connection_is_bidirectionally_valid(connection, source_marker):
            raise ValueError("World travel source anchor is not a connected exit")
        position = self.runtime_scene.world_transform(actor.entity_id).position
        if connection.transition is TransitionMode.SEAMLESS and not _inside_anchor_trigger(
            position,
            source_position,
            self.runtime_scene.world_transform(source_entity.entity_id),
            source_marker,
        ):
            raise ValueError("seamless travel requires the actor to be at the connected exit")
        pending = PendingWorldTransition(
            anchor_id,
            connection,
            source_position,
            persistent_id,
            actor.entity_id,
            manual=True,
        )
        self._pending_transitions[anchor_id] = pending
        if self._residency.state(connection.destination_level_id).state in {
            LevelResidencyState.UNLOADED,
            LevelResidencyState.CANCELLED,
        }:
            self._request_pending_destination(connection.destination_level_id)
        self._start_world_transition(pending, actor)
        return True

    def _advance_seamless_connections(
        self, anchors: tuple[StreamingAnchor, ...]
    ) -> None:
        portal_positions = self.portal_positions()
        for anchor in anchors:
            if anchor.entity_id is None:
                continue
            actor = self.runtime_scene.find_entity(anchor.entity_id)
            persistent_id = self._persistent_id_for_entity(anchor.entity_id)
            if (
                actor is None
                or persistent_id is None
                or self._persistent_actor_roots.get(persistent_id) != actor.entity_id
            ):
                continue
            position = self.runtime_scene.world_transform(actor.entity_id).position
            pending = self._pending_transitions.get(anchor.anchor_id)
            if pending is not None:
                connection = pending.connection
                key = (connection.source_level_id, connection.source_anchor_id)
                portal_entity = self._active_anchor_entity(*key)
                marker = portal_entity.get_component(LevelAnchorComponent) if portal_entity else None
                portal = portal_positions.get(key)
                if marker is None or portal is None:
                    self._pending_transitions.pop(anchor.anchor_id, None)
                    self._last_transition_error = (
                        f"pending connection {connection.connection_id!r} lost its source anchor"
                    )
                    continue
                pose = self.runtime_scene.world_transform(portal_entity.entity_id)
                if not pending.manual and not _inside_anchor_trigger(position, portal, pose, marker):
                    self._pending_transitions.pop(anchor.anchor_id, None)
                    self._last_safe_anchor_positions[anchor.anchor_id] = position
                    continue
                destination_state = self._residency.state(connection.destination_level_id)
                if destination_state.state not in {
                    LevelResidencyState.LOADED,
                    LevelResidencyState.ACTIVE,
                    LevelResidencyState.DORMANT,
                }:
                    if destination_state.state in {
                        LevelResidencyState.UNLOADED,
                        LevelResidencyState.CANCELLED,
                    }:
                        self._request_pending_destination(connection.destination_level_id)
                    if not pending.manual:
                        _set_root_world_position(actor, pending.blocking_position)
                        self._last_safe_anchor_positions[anchor.anchor_id] = pending.blocking_position
                    if destination_state.state is LevelResidencyState.FAILED:
                        self._last_transition_error = (
                            f"destination Level {connection.destination_level_id!r} failed to load; "
                            "retry explicitly"
                        )
                    else:
                        self._last_transition_error = (
                            f"waiting for destination Level {connection.destination_level_id!r}"
                        )
                    self._start_world_transition(pending, actor)
                    continue
                self._start_world_transition(pending, actor)
                continue

            previous = self._last_safe_anchor_positions.get(anchor.anchor_id)
            if previous is None:
                self._last_safe_anchor_positions[anchor.anchor_id] = position
                continue
            for connection in self.world.connections_from(anchor.level_id, include_reverse=True):
                key = (connection.source_level_id, connection.source_anchor_id)
                source_position = portal_positions.get(key)
                source_marker_entity = self._active_anchor_entity(*key)
                if source_position is None or source_marker_entity is None:
                    continue
                marker = source_marker_entity.get_component(LevelAnchorComponent)
                assert marker is not None
                source_pose = self.runtime_scene.world_transform(source_marker_entity.entity_id)
                previous_inside = (
                    previous is not None
                    and _inside_anchor_trigger(
                        previous,
                        source_position,
                        source_pose,
                        marker,
                    )
                )
                if previous_inside:
                    continue
                if not _segment_intersects_anchor_trigger(
                    previous, anchor.position, source_position, source_pose, marker
                ):
                    continue
                if not self._connection_is_bidirectionally_valid(connection, marker):
                    self._last_transition_error = (
                        f"connection {connection.connection_id!r} source anchor is not an exit"
                    )
                    continue
                destination_state = self._residency.state(connection.destination_level_id)
                if destination_state.state not in {
                    LevelResidencyState.LOADED,
                    LevelResidencyState.ACTIVE,
                    LevelResidencyState.DORMANT,
                }:
                    pending = PendingWorldTransition(
                        anchor.anchor_id,
                        connection,
                        source_position,
                        persistent_id,
                        actor.entity_id,
                    )
                    self._pending_transitions[anchor.anchor_id] = pending
                    if destination_state.state in {
                        LevelResidencyState.UNLOADED,
                        LevelResidencyState.CANCELLED,
                    }:
                        self._request_pending_destination(connection.destination_level_id)
                    _set_root_world_position(actor, source_position)
                    self._last_safe_anchor_positions[anchor.anchor_id] = source_position
                    self._last_transition_error = (
                        f"destination Level {connection.destination_level_id!r} failed to load; "
                        "retry explicitly"
                        if destination_state.state is LevelResidencyState.FAILED
                        else f"waiting for destination Level {connection.destination_level_id!r}"
                    )
                    self._start_world_transition(pending, actor)
                    continue
                pending = PendingWorldTransition(
                    anchor.anchor_id,
                    connection,
                    source_position,
                    persistent_id,
                    actor.entity_id,
                )
                self._pending_transitions[anchor.anchor_id] = pending
                if self._start_world_transition(pending, actor):
                    break
            else:
                if not any(
                    _inside_anchor_trigger(
                        anchor.position,
                        portal_positions[key],
                        self.runtime_scene.world_transform(entity.entity_id),
                        entity.get_component(LevelAnchorComponent),
                    )
                    for key in portal_positions
                    if key[0] == anchor.level_id
                    and (entity := self._active_anchor_entity(*key)) is not None
                    and entity.get_component(LevelAnchorComponent) is not None
                ):
                    self._last_safe_anchor_positions[anchor.anchor_id] = position

    def _request_pending_destination(self, level_id: str) -> None:
        try:
            self._schedule_load(
                level_id,
                priority=self._descriptors[level_id].priority + 1_000_000,
            )
        except ResidencyCapacityError as error:
            self._last_transition_error = (
                f"connection destination {level_id!r} is blocked by the World residency budget: {error}"
            )

    def _start_world_transition(
        self,
        pending: PendingWorldTransition,
        actor: Entity,
    ) -> bool:
        connection = pending.connection
        destination_state = self._residency.state(connection.destination_level_id).state
        active_status = self._transition_controller.status
        if active_status in {
            TransitionStatus.PREPARING,
            TransitionStatus.FADING_OUT,
            TransitionStatus.SWITCHING,
            TransitionStatus.FADING_IN,
        }:
            if self._active_transition_anchor_id != pending.anchor_id:
                return False
            self._advance_active_transition(0.0)
            return True
        if destination_state is LevelResidencyState.FAILED:
            self._last_transition_error = (
                f"destination Level {connection.destination_level_id!r} failed to load; retry explicitly"
            )
            return False
        self._transition_controller.begin(
            connection.connection_id,
            connection.source_level_id,
            connection.destination_level_id,
            connection.transition,
        )
        self._active_transition_anchor_id = pending.anchor_id
        if connection.transition is TransitionMode.FADE and not pending.manual:
            _set_root_world_position(actor, pending.blocking_position)
        self._advance_active_transition(0.0)
        return True

    def _advance_active_transition(self, dt: float) -> None:
        if self._active_transition_anchor_id is None:
            return
        controller = self._transition_controller
        status = controller.status
        if status is TransitionStatus.PREPARING:
            anchor_id = self._active_transition_anchor_id
            pending = self._pending_transitions.get(anchor_id)
            if pending is None:
                controller.fail("pending transition data was lost")
                return
            destination = self._residency.state(pending.connection.destination_level_id)
            if destination.state is LevelResidencyState.FAILED:
                controller.fail(destination.error or "destination Level failed to load")
                self._last_transition_error = controller.error
                return
            if destination.state in {
                LevelResidencyState.LOADED,
                LevelResidencyState.ACTIVE,
                LevelResidencyState.DORMANT,
            }:
                destination_anchor = self._source_anchor_position(
                    pending.connection.destination_level_id,
                    pending.connection.destination_anchor_id,
                )
                if destination_anchor is None:
                    controller.fail(
                        f"connection {pending.connection.connection_id!r} destination anchor is missing"
                    )
                    self._last_transition_error = controller.error
                    self._pending_transitions.pop(anchor_id, None)
                    self._active_transition_anchor_id = None
                    return
                if (
                    pending.connection.transition is TransitionMode.SEAMLESS
                    and math.dist(pending.blocking_position, destination_anchor) > 0.01
                ):
                    controller.fail("seamless connection endpoints are not physically adjacent")
                    self._last_transition_error = controller.error
                    self._pending_transitions.pop(anchor_id, None)
                    self._active_transition_anchor_id = None
                    return
                controller.destination_ready()
                status = controller.status
        controller.advance(dt)
        if controller.status is TransitionStatus.SWITCHING and controller.advance(0.0):
            anchor_id = self._active_transition_anchor_id
            pending = self._pending_transitions.get(anchor_id)
            if pending is None:
                controller.fail("pending transition data was lost")
                self._last_transition_error = controller.error
                return
            actor = self.runtime_scene.find_entity(pending.actor_entity_id)
            if actor is None:
                controller.fail("World-persistent actor is no longer active")
                self._last_transition_error = controller.error
                self._pending_transitions.pop(anchor_id, None)
                return
            try:
                self._commit_world_transition(pending, actor)
            except (RuntimeError, ValueError) as error:
                controller.fail(f"{type(error).__name__}: {str(error)[:180]}")
                self._last_transition_error = controller.error
                self._pending_transitions.pop(anchor_id, None)
                return
            controller.complete_switch()
            self._pending_transitions.pop(anchor_id, None)
            self._last_transition_error = None
            if controller.status is TransitionStatus.COMPLETE:
                self._active_transition_anchor_id = None
        elif controller.status in {TransitionStatus.COMPLETE, TransitionStatus.FAILED}:
            self._active_transition_anchor_id = None
            if controller.status is TransitionStatus.FAILED:
                self._last_transition_error = controller.error

    def _commit_world_transition(
        self, pending: PendingWorldTransition, actor: Entity
    ) -> None:
        anchor_id = pending.anchor_id
        persistent_id = pending.persistent_id
        connection = pending.connection
        source_position = pending.blocking_position
        destination_anchor = self._source_anchor_position(
            connection.destination_level_id,
            connection.destination_anchor_id,
        )
        if destination_anchor is None:
            raise ValueError(f"connection {connection.connection_id!r} destination anchor is missing")
        if (
            connection.transition is TransitionMode.SEAMLESS
            and math.dist(source_position, destination_anchor) > 0.01
        ):
            raise ValueError("seamless connection endpoints are not physically adjacent")
        if (
            self._residency.state(connection.destination_level_id).state
            is not LevelResidencyState.ACTIVE
            and not self.activate_level(connection.destination_level_id)
        ):
            raise RuntimeError(f"destination Level {connection.destination_level_id!r} could not activate")
        if connection.transition is not TransitionMode.SEAMLESS:
            _set_root_world_position(actor, destination_anchor)
            destination_entity = self._active_anchor_entity(
                connection.destination_level_id, connection.destination_anchor_id
            )
            destination_marker = (
                destination_entity.get_component(LevelAnchorComponent)
                if destination_entity is not None
                else None
            )
            transform = actor.get_component(TransformComponent)
            if transform is not None and destination_marker is not None:
                transform.rotation = self.runtime_scene.world_transform(
                    destination_entity.entity_id
                ).rotation
            self._camera_context_level_id = connection.destination_level_id
            self._camera_recenter_generation += 1
        self._persistent_actor_levels[persistent_id] = connection.destination_level_id
        self._last_transition = (
            connection.source_level_id,
            connection.destination_level_id,
            connection.connection_id,
        )
        self._handover_holds[connection.source_level_id] = 1
        self._new_handover_sources.add(connection.source_level_id)
        self._last_safe_anchor_positions[anchor_id] = destination_anchor

    def _active_anchor_entity(self, level_id: str, anchor_id: str) -> Entity | None:
        if self._residency.state(level_id).state is not LevelResidencyState.ACTIVE:
            return None
        entity_ids = list(self._level_portal_entity_ids.get(level_id, ()))
        entity_ids.extend(
            entity_id
            for entity_id, persistent_id in self._persistent_portal_owners.items()
            if self._persistent_actor_levels.get(persistent_id) == level_id
        )
        for entity_id in entity_ids:
            entity = self.runtime_scene.find_entity(entity_id)
            marker = entity.get_component(LevelAnchorComponent) if entity is not None else None
            if marker is not None and marker.enabled and marker.anchor_id == anchor_id:
                return entity
        return None

    def _source_anchor_position(self, level_id: str, anchor_id: str) -> tuple[float, float] | None:
        active_entity = self._active_anchor_entity(level_id, anchor_id)
        if active_entity is not None:
            return self.runtime_scene.world_transform(active_entity.entity_id).position
        level = self._prepared_or_dormant_level(level_id)
        found = level.find_anchor(anchor_id) if level is not None else None
        if found is None:
            return None
        return level.world_transform(found[0].entity_id).position

    def _prepared_or_dormant_level(self, level_id: str) -> Level | None:
        level = self._runtime_levels.get(level_id)
        if level is not None and level.entities:
            return level
        prepared = self._prepared_levels.get(level_id)
        return prepared[1] if prepared is not None else level

    def _connection_is_bidirectionally_valid(
        self, connection: WorldConnection, marker: LevelAnchorComponent
    ) -> bool:
        if connection.connection_id.endswith(":reverse"):
            return marker.kind in {LevelAnchorKind.ENTRANCE, LevelAnchorKind.BOTH}
        return marker.kind in {LevelAnchorKind.EXIT, LevelAnchorKind.BOTH}
