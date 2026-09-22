"""Presentation render orchestration for the Tk UI.

Adapted from System Analyzer maintenance/ui/render_coordinator.py
(UICoordinator, RenderIntent).

UI COORDINATOR OWNS PRESENTATION.

Batches render commits, coalesces repeated requests for the same target,
and drops stale presentation generations before a widget commit can run.
The coordinator never scans, schedules workers, or mutates widgets itself.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from expra_engine.coordinators.transition import PendingTransition
from expra_engine.observability import EventKind, ObservabilityWatcher, Outcome

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RenderIntent:
    """Small dirty-field description for one presentation commit."""

    target: str
    generation: int = 0
    owner_id: Any | None = None
    components: frozenset[str] = frozenset()
    layout_changed: bool = False
    style_changed: bool = False
    payload: Any | None = None
    payload_set: bool = False
    priority: int = 0

    def merge(self, other: RenderIntent) -> RenderIntent:
        if self.target != other.target:
            raise ValueError("Cannot merge render intents for different targets")
        return RenderIntent(
            target=self.target,
            generation=max(self.generation, other.generation),
            owner_id=other.owner_id if other.owner_id is not None else self.owner_id,
            components=self.components | other.components,
            layout_changed=self.layout_changed or other.layout_changed,
            style_changed=self.style_changed or other.style_changed,
            payload=other.payload if other.payload_set else self.payload,
            payload_set=self.payload_set or other.payload_set,
            priority=max(self.priority, other.priority),
        )


@dataclass(slots=True)
class _PendingRender:
    intent: RenderIntent
    apply: Callable[[RenderIntent], None]


class UICoordinator:
    """Batch and coalesce presentation commits on the UI thread.

    In the game editor, targets correspond to editor panels:
    ``"hierarchy"``, ``"inspector"``, ``"viewport"``, ``"assets"``,
    ``"console"``, ``"toolbar"``, ``"status"``.

    Callers queue render intents; the coordinator drops stale ones,
    coalesces duplicate targets, and commits at the flush boundary.
    """

    def __init__(
        self,
        *,
        schedule: Callable[[int, Callable[[], None]], Any] | None = None,
        cancel: Callable[[Any], bool] | None = None,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        self._pending: dict[str, _PendingRender] = {}
        self._visible: dict[str, bool] = {}
        self._generations: dict[str, int] = {}
        self._target_nodes: dict[str, Any | None] = {}
        self._batch_depth = 0
        self._flushing = False
        self._flush_scheduled = False
        self._closed = False
        self.pending_peak = 0
        self.last_commit_seconds = 0.0
        self._observer = observer or ObservabilityWatcher()
        self._schedule = schedule or (lambda _delay, _callback: None)
        self._cancel = cancel or (lambda _identifier: False)
        self._transitions: dict[str, PendingTransition] = {}

    def _event_total(self, event: EventKind) -> int:
        return self._observer.event_total("ui:render:", event)

    @property
    def render_requests(self) -> int:
        return self._event_total("request")

    @property
    def render_commits(self) -> int:
        return self._event_total("commit")

    @property
    def coalesced_requests(self) -> int:
        return self._event_total("coalesced")

    @property
    def stale_rejections(self) -> int:
        return self._event_total("stale")

    @property
    def render_failures(self) -> int:
        return self._event_total("failure")

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def begin_batch(self) -> None:
        if not self._closed:
            self._batch_depth += 1

    def end_batch(self) -> None:
        if self._batch_depth == 0:
            return
        self._batch_depth -= 1
        if self._batch_depth == 0:
            self.flush()

    def set_visible(self, target: str, visible: bool) -> None:
        self._visible[target] = visible
        if visible and self._batch_depth == 0:
            self.flush()

    def invalidate(
        self,
        target: str,
        generation: int | None = None,
        owner_id: Any | None = None,
    ) -> None:
        current = self._generations.get(target, 0)
        previous_owner = self._target_nodes.get(target)
        owner_changed = (
            owner_id is not None and previous_owner is not None and previous_owner != owner_id
        )
        next_generation = (
            generation
            if owner_changed and generation is not None
            else current + 1
            if generation is None
            else max(current, generation)
        )
        self._generations[target] = next_generation
        if owner_id is not None:
            self._target_nodes[target] = owner_id
            if owner_changed:
                self._pending.pop(target, None)
        pending = self._pending.get(target)
        if pending is not None and pending.intent.generation < next_generation:
            del self._pending[target]
        if (
            pending is not None
            and owner_id is not None
            and pending.intent.owner_id is not None
            and pending.intent.owner_id != owner_id
        ):
            del self._pending[target]

    def clear(self, target: str | None = None) -> None:
        if target is None:
            self._pending.clear()
            self._generations.clear()
            self._visible.clear()
            self._target_nodes.clear()
            return
        self._pending.pop(target, None)
        self._visible.pop(target, None)
        self._target_nodes.pop(target, None)
        self._generations[target] = self._generations.get(target, 0) + 1

    def shutdown(self) -> None:
        self._closed = True
        self.clear()
        for transition in self._transitions.values():
            transition.cancel()
        self._transitions.clear()

    def schedule_transition(self, name: str, delay: int, apply: Callable[[], None]) -> None:
        if name not in self._transitions:
            self._transitions[name] = PendingTransition(self._schedule, self._cancel)
        self._transitions[name].start(delay, apply)

    def cancel_transition(self, name: str) -> None:
        transition = self._transitions.get(name)
        if transition is not None:
            transition.cancel()

    def request(
        self,
        intent: RenderIntent,
        apply: Callable[[RenderIntent], None],
    ) -> bool:
        if self._closed:
            self._record_event(intent.target, "rejected")
            return False

        current = self._generations.get(intent.target, 0)
        if intent.generation < current:
            self._record_event(intent.target, "stale")
            return False
        if intent.generation > current:
            self._generations[intent.target] = intent.generation

        owner = self._target_nodes.get(intent.target)
        if owner is not None and intent.owner_id is not None and owner != intent.owner_id:
            self._record_event(intent.target, "stale")
            return False
        if intent.owner_id is not None and owner is None:
            self._target_nodes[intent.target] = intent.owner_id

        pending = self._pending.get(intent.target)
        if pending is None:
            self._pending[intent.target] = _PendingRender(intent=intent, apply=apply)
        else:
            if (
                pending.intent.owner_id is not None
                and intent.owner_id is not None
                and pending.intent.owner_id != intent.owner_id
            ):
                self._pending[intent.target] = _PendingRender(
                    intent=intent,
                    apply=apply,
                )
            else:
                self._record_event(intent.target, "coalesced")
                self._pending[intent.target] = _PendingRender(
                    intent=pending.intent.merge(intent),
                    apply=apply,
                )
        self._record_event(intent.target, "request")
        self.pending_peak = max(self.pending_peak, len(self._pending))

        if (
            self._batch_depth == 0
            and not self._flushing
            and not self._flush_scheduled
            and self._visible.get(intent.target, True)
        ):
            token = self._schedule(0, self._deferred_flush)
            if token is not None:
                self._flush_scheduled = True
            else:
                self._apply_target(intent.target)
        return True

    def _deferred_flush(self) -> None:
        self._flush_scheduled = False
        if not self._closed:
            self.flush()

    def flush(self) -> None:
        if self._closed:
            return

        self._flushing = True
        try:
            while True:
                ready = [
                    (target, pending)
                    for target, pending in self._pending.items()
                    if self._visible.get(target, True)
                    and pending.intent.generation >= self._generations.get(target, 0)
                ]
                if not ready:
                    return
                ready.sort(
                    key=lambda item: (
                        -item[1].intent.priority,
                        item[1].intent.target,
                    )
                )
                target = ready[0][0]
                if not self._apply_target(target) and target in self._pending:
                    return
        finally:
            self._flushing = False

    def _apply_target(self, target: str) -> bool:
        pending = self._pending.get(target)
        if pending is None:
            return False
        current = self._generations.get(target, 0)
        if pending.intent.generation < current:
            self._record_event(target, "stale")
            del self._pending[target]
            return False
        owner = self._target_nodes.get(target)
        if (
            owner is not None
            and pending.intent.owner_id is not None
            and owner != pending.intent.owner_id
        ):
            self._record_event(target, "stale")
            del self._pending[target]
            return False
        if not self._visible.get(target, True):
            return False

        del self._pending[target]
        token = self._observer.begin(f"ui:render:{target}") if self._observer is not None else None
        started = time.perf_counter()
        outcome: Outcome = "success"
        detail: str | None = None
        try:
            pending.apply(pending.intent)
        except Exception as error:  # noqa: BLE001
            outcome = "failure"
            detail = type(error).__name__
            self._record_event(target, "failure")
            LOGGER.warning("Render commit for %s failed: %s", target, error)
        finally:
            self.last_commit_seconds = time.perf_counter() - started
            if token is not None:
                observer = self._observer
                assert observer is not None
                observer.finish(
                    token,
                    outcome=outcome,
                    duration_seconds=self.last_commit_seconds,
                    detail=detail,
                )
        self._record_event(target, "commit")
        return True

    def _record_event(self, target: str, event: EventKind) -> None:
        self._observer.record_event(f"ui:render:{target}", event)
