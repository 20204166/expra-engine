"""Anchor registry, portal index and streaming policy, owned by WorldStreamingSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING

from expra_engine.runtime.level_anchor import LevelAnchorComponent, StreamingAnchorComponent
from expra_engine.runtime.world_policy import (
    LevelResidencyState,
    ResidencyCapacityError,
    StreamingAnchor,
    StreamingDecision,
)

if TYPE_CHECKING:
    pass

__all__ = ("WorldAnchorPolicyMixin",)


class WorldAnchorPolicyMixin:
    """Anchor registry, portal index and streaming policy for WorldStreamingSystem.

    Split from ``world_streaming.py`` as the canonical anchor/policy
    responsibility. Operates on the hosting system's residency, scene, and
    descriptor state; introduces no parallel systems.
    """

    def register_anchor(self, anchor: StreamingAnchor) -> None:
        """Register a non-Entity anchor such as a spectator or editor preview."""
        self._assert_owner()
        if anchor.level_id not in self._descriptors:
            raise ValueError("streaming anchor references an unknown Level")
        self._external_anchors[anchor.anchor_id] = anchor

    def unregister_anchor(self, anchor_id: str) -> bool:
        self._assert_owner()
        return self._external_anchors.pop(anchor_id, None) is not None

    def streaming_anchors(self) -> tuple[StreamingAnchor, ...]:
        """Resolve Entity anchors through canonical World-space pose ownership."""
        resolved = dict(self._external_anchors)
        for level_id, entity_ids in self._level_streaming_anchor_ids.items():
            if self._residency.state(level_id).state is not LevelResidencyState.ACTIVE:
                continue
            for entity_id in entity_ids:
                self._add_entity_streaming_anchor(resolved, level_id, entity_id)
        for entity_id, persistent_id in self._persistent_streaming_anchor_owners.items():
            level_id = self._persistent_actor_levels.get(persistent_id)
            if level_id is not None:
                self._add_entity_streaming_anchor(resolved, level_id, entity_id)
        return tuple(resolved[key] for key in sorted(resolved))

    def portal_positions(self) -> dict[tuple[str, str], tuple[float, float]]:
        """Return active named anchors in World coordinates for graph policy."""
        result: dict[tuple[str, str], tuple[float, float]] = {}
        for level_id, entity_ids in self._level_portal_entity_ids.items():
            if self._residency.state(level_id).state is not LevelResidencyState.ACTIVE:
                continue
            for entity_id in entity_ids:
                self._add_portal_position(result, level_id, entity_id)
        for entity_id, persistent_id in self._persistent_portal_owners.items():
            level_id = self._persistent_actor_levels.get(persistent_id)
            if level_id is not None:
                self._add_portal_position(result, level_id, entity_id)
        return result

    def _index_level_anchors(
        self,
        level_id: str,
        level_entity_ids: tuple[str, ...],
        persistent_entity_ids: tuple[str, ...],
    ) -> None:
        streaming: list[str] = []
        portals: list[str] = []
        for entity_id in level_entity_ids:
            entity = self.runtime_scene.find_entity(entity_id)
            if entity is None:
                continue
            if entity.get_component(StreamingAnchorComponent) is not None:
                streaming.append(entity_id)
            if entity.get_component(LevelAnchorComponent) is not None:
                portals.append(entity_id)
        self._level_streaming_anchor_ids[level_id] = tuple(streaming)
        self._level_portal_entity_ids[level_id] = tuple(portals)
        for entity_id in persistent_entity_ids:
            persistent_id = self._persistent_id_for_entity(entity_id)
            entity = self.runtime_scene.find_entity(entity_id)
            if persistent_id is None or entity is None:
                continue
            if entity.get_component(StreamingAnchorComponent) is not None:
                self._persistent_streaming_anchor_owners[entity_id] = persistent_id
            if entity.get_component(LevelAnchorComponent) is not None:
                self._persistent_portal_owners[entity_id] = persistent_id

    def _add_entity_streaming_anchor(
        self,
        resolved: dict[str, StreamingAnchor],
        level_id: str,
        entity_id: str,
    ) -> None:
        entity = self.runtime_scene.find_entity(entity_id)
        marker = entity.get_component(StreamingAnchorComponent) if entity is not None else None
        if entity is None or marker is None or not entity.enabled or not marker.enabled:
            return
        if marker.anchor_id in resolved:
            raise ValueError(f"duplicate World streaming anchor ID: {marker.anchor_id!r}")
        resolved[marker.anchor_id] = StreamingAnchor(
            marker.anchor_id,
            level_id,
            self.runtime_scene.world_transform(entity_id).position,
            entity_id,
        )

    def _add_portal_position(
        self,
        result: dict[tuple[str, str], tuple[float, float]],
        level_id: str,
        entity_id: str,
    ) -> None:
        entity = self.runtime_scene.find_entity(entity_id)
        marker = entity.get_component(LevelAnchorComponent) if entity is not None else None
        if entity is None or marker is None or not entity.enabled or not marker.enabled:
            return
        key = (level_id, marker.anchor_id)
        if key in result:
            raise ValueError(f"duplicate active Level anchor: {key!r}")
        result[key] = self.runtime_scene.world_transform(entity_id).position

    def current_level(self, anchor_id: str) -> str | None:
        """Return the Level context for one registered streaming anchor."""
        anchor = next(
            (item for item in self.streaming_anchors() if item.anchor_id == anchor_id), None
        )
        return anchor.level_id if anchor is not None else None

    def pin_level(self, level_id: str) -> int:
        """Keep one declared Level resident until explicit ``unpin_level``."""
        self._assert_owner()
        if level_id not in self._descriptors:
            raise KeyError(f"unknown World Level instance: {level_id!r}")
        self._pinned_levels.add(level_id)
        return self._schedule_load(
            level_id, priority=self._descriptors[level_id].priority + 500_000
        )

    def unpin_level(self, level_id: str) -> bool:
        self._assert_owner()
        if level_id not in self._pinned_levels:
            return False
        self._pinned_levels.remove(level_id)
        return True

    def _reconcile_streaming_policy(self) -> None:
        _obs = self._observer
        _pt = _obs.begin("world:streaming:policy") if _obs is not None else None
        try:
            self._reconcile_streaming_policy_inner()
        finally:
            if _obs is not None and _pt is not None:
                _obs.finish(_pt)  # type: ignore[arg-type]

    def _reconcile_streaming_policy_inner(self) -> None:
        anchors = self.streaming_anchors()
        if self._startup_level_id is not None and any(
            anchor.level_id == self._startup_level_id for anchor in anchors
        ):
            self._startup_level_id = None
        self._request_policy_residency(anchors)
        self._advance_seamless_connections(anchors)
        anchors = self.streaming_anchors()
        decision = self._policy_decision(anchors)
        self._last_decision = decision
        desired_active = set(decision.active_level_ids) | set(self._handover_holds)
        for level_id in self.active_levels():
            if level_id not in desired_active:
                self.deactivate_level(level_id)
        for level_id in decision.active_level_ids:
            state = self._residency.state(level_id).state
            if state in {LevelResidencyState.LOADED, LevelResidencyState.DORMANT}:
                self.activate_level(level_id)
        for level_id in self.loaded_levels():
            if level_id not in decision.resident_level_ids and level_id not in (
                self._pinned_levels | self._manual_requests
            ):
                self.unload_level(level_id)
        for level_id in tuple(self._handover_holds):
            if level_id in self._new_handover_sources:
                continue
            remaining = self._handover_holds[level_id] - 1
            if remaining <= 0:
                del self._handover_holds[level_id]
            else:
                self._handover_holds[level_id] = remaining
        self._new_handover_sources.clear()
        _obs = getattr(self, "_observer", None)
        if _obs is not None:
            snapshots = self._residency.snapshots()
            _obs.set_gauge(
                "world:streaming:policy",
                "active_levels",
                sum(1 for s in snapshots if s.state is LevelResidencyState.ACTIVE),
            )
            _obs.set_gauge(
                "world:streaming:policy",
                "dormant_levels",
                sum(1 for s in snapshots if s.state is LevelResidencyState.DORMANT),
            )
            _obs.set_gauge(
                "world:streaming:policy",
                "loading_levels",
                sum(1 for s in snapshots if s.state is LevelResidencyState.LOADING),
            )
            _obs.set_gauge(
                "world:streaming:policy",
                "queued_levels",
                sum(1 for s in snapshots if s.state is LevelResidencyState.QUEUED),
            )
            _obs.set_gauge(
                "world:streaming:policy",
                "failed_levels",
                sum(1 for s in snapshots if s.state is LevelResidencyState.FAILED),
            )
            _obs.set_gauge(
                "world:streaming:policy", "resident_levels", float(len(self.loaded_levels()))
            )
            _obs.set_gauge(
                "world:streaming:policy", "pending_loads", float(len(getattr(self, "_pending", {})))
            )
            _obs.set_gauge(
                "world:streaming:policy",
                "pinned_levels",
                float(len(getattr(self, "_pinned_levels", set()))),
            )

    def _request_policy_residency(self, anchors: tuple[StreamingAnchor, ...]) -> None:
        decision = self._policy_decision(anchors)
        for level_id in decision.resident_level_ids:
            state = self._residency.state(level_id).state
            if state in {
                LevelResidencyState.UNLOADED,
                LevelResidencyState.CANCELLED,
            }:
                descriptor = self._descriptors[level_id]
                priority = descriptor.priority
                if level_id in decision.active_level_ids:
                    priority += 1_000_000
                elif level_id in decision.preload_level_ids:
                    priority += 100_000
                self._schedule_load(level_id, priority=priority)
        for level_id in tuple(set(self._pending) | set(self._futures)):
            if level_id not in decision.resident_level_ids and level_id not in (
                self._manual_requests | self._pinned_levels
            ):
                self.cancel_load(level_id)

    def _policy_decision(self, anchors: tuple[StreamingAnchor, ...]) -> StreamingDecision:
        pending_destinations = {
            item.connection.destination_level_id for item in self._pending_transitions.values()
        }
        try:
            return self._policy.decide(
                self.world,
                anchors,
                self.portal_positions(),
                resident_level_ids=self._resident_level_ids(),
                pinned_level_ids=tuple(
                    self._pinned_levels
                    | self._manual_requests
                    | pending_destinations
                    | self._persistent_bootstrap_level_ids
                ),
                initial_level_id=self._startup_level_id,
            )
        except ResidencyCapacityError as error:
            if pending_destinations:
                self._last_transition_error = (
                    f"pending seamless travel exceeds World residency budget: {error}"
                )
                return self._policy.decide(
                    self.world,
                    anchors,
                    self.portal_positions(),
                    resident_level_ids=self._resident_level_ids(),
                    pinned_level_ids=tuple(
                        self._pinned_levels
                        | self._manual_requests
                        | self._persistent_bootstrap_level_ids
                    ),
                    initial_level_id=self._startup_level_id,
                )
            raise

    def _resident_level_ids(self) -> tuple[str, ...]:
        return tuple(
            item.level_id
            for item in self._residency.snapshots()
            if item.state
            in {
                LevelResidencyState.QUEUED,
                LevelResidencyState.LOADING,
                LevelResidencyState.LOADED,
                LevelResidencyState.ACTIVE,
                LevelResidencyState.DORMANT,
            }
        )

    def _persistent_id_for_entity(self, entity_id: str) -> str | None:
        for persistent_id, entity_ids in self._persistent_actor_entity_ids.items():
            if entity_id in entity_ids:
                return persistent_id
        return None
