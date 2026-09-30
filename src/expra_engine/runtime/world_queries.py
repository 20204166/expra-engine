"""Read-only residency and startup queries for a World streaming session."""

from __future__ import annotations

from typing import Any, Protocol

from expra_engine.runtime.world_policy import (
    LevelResidencyManager,
    LevelResidencySnapshot,
    LevelResidencyState,
    PendingWorldTransition,
    StreamingAnchor,
    StreamingDecision,
    World,
    WorldCameraContext,
    WorldStreamingSnapshot,
)
from expra_engine.runtime.world_transition import WorldTransitionSnapshot

__all__ = ("WorldStreamingQueriesMixin",)


class _WorldStreamingQueryHost(Protocol):
    world: World
    _residency: LevelResidencyManager
    _started: bool
    _pending: dict[str, Any]
    _futures: dict[str, Any]
    _stale_results_discarded: int
    _last_decision: StreamingDecision
    _last_transition: tuple[str, str, str] | None
    _last_transition_error: str | None
    _pending_transitions: dict[str, PendingWorldTransition]
    _session_state: Any
    _last_session_error: str | None
    _startup_level_id: str | None
    _startup_error: str | None
    _startup_diagnostic: str | None

    def streaming_anchors(self) -> tuple[StreamingAnchor, ...]: ...

    @property
    def camera_context(self) -> WorldCameraContext: ...

    @property
    def transition(self) -> WorldTransitionSnapshot: ...


class WorldStreamingQueriesMixin:
    """Expose the streaming system's canonical state without duplicating it."""

    def state(self: _WorldStreamingQueryHost, level_id: str) -> LevelResidencySnapshot:
        return self._residency.state(level_id)

    def loaded_levels(self: _WorldStreamingQueryHost) -> tuple[str, ...]:
        return tuple(
            item.level_id
            for item in self._residency.snapshots()
            if item.state
            in {
                LevelResidencyState.LOADED,
                LevelResidencyState.ACTIVE,
                LevelResidencyState.DORMANT,
            }
        )

    def active_levels(self: _WorldStreamingQueryHost) -> tuple[str, ...]:
        return tuple(
            item.level_id
            for item in self._residency.snapshots()
            if item.state is LevelResidencyState.ACTIVE
        )

    def snapshot(self: _WorldStreamingQueryHost) -> WorldStreamingSnapshot:
        anchors = self.streaming_anchors() if self._started else ()
        return WorldStreamingSnapshot(
            world_id=self.world.world_id,
            levels=self._residency.snapshots(),
            pending_level_ids=tuple(sorted(self._pending)),
            in_flight_level_ids=tuple(sorted(self._futures)),
            stale_results_discarded=self._stale_results_discarded,
            max_concurrent_loads=self.world.streaming.max_concurrent_loads,
            max_resident_levels=self.world.streaming.max_loaded_levels,
            primary_levels=tuple(sorted((anchor.anchor_id, anchor.level_id) for anchor in anchors)),
            residency_reasons=self._last_decision.reasons,
            last_transition=self._last_transition,
            last_transition_error=self._last_transition_error,
            connection_preloads=self._last_decision.preload_level_ids,
            camera=self.camera_context,
            pending_transitions=tuple(
                self._pending_transitions[key] for key in sorted(self._pending_transitions)
            ),
            session_state_counts=tuple(
                (level_id, len(values))
                for level_id, values in sorted(self._session_state.levels.items())
            ),
            last_session_error=self._last_session_error,
            transition=self.transition,
        )

    @property
    def startup_level_id(self: _WorldStreamingQueryHost) -> str | None:
        """The Level selected for this fresh or restored World session."""
        return self._startup_level_id

    @property
    def startup_error(self: _WorldStreamingQueryHost) -> str | None:
        """A failure that prevented the selected startup Level from activating."""
        return self._startup_error

    @property
    def startup_diagnostic(self: _WorldStreamingQueryHost) -> str | None:
        """A non-fatal startup configuration issue, if the Level can still render."""
        return self._startup_diagnostic
