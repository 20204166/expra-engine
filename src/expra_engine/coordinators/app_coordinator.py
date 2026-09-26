"""Universal per-key shock absorber between background work and the UI.

Adapted from System Analyzer maintenance/components/coordinator.py
(AppCoordinator).

Removed: discovery/network lifecycle methods, PlacementPolicy dependency.
Preserved: coalescing, caching, cancellation, generation safety, delivery
boundary, subscriber pattern, deferred triggers, post/post_coalesced.

APP COORDINATOR OWNS WORK. Background work never touches widgets.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from expra_engine.observability import (
    EventKind,
    ObservabilityWatcher,
    ObservationToken,
    Outcome,
)

LOGGER = logging.getLogger(__name__)


class CachePolicy(Enum):
    """Explicit cache behavior for one coordinated operation."""

    NONE = "none"
    STALE_WHILE_REFRESH = "stale_while_refresh"


@dataclass
class AppRunState:
    """Per-key runtime state for one coordinated background operation."""

    in_flight: bool = False
    generation: int = 0
    rerun_requested: bool = False
    cancelled: bool = False
    cancel_event: threading.Event | None = None
    future: Future[Any] | None = None
    last_result: Any | None = None
    subscribers: list[Callable[[str, Any | None], None]] | None = field(default=None)
    on_result: Callable[[str, Any], None] | None = None
    on_error: Callable[[str, str], None] | None = None
    on_progress: Callable[[str, str], None] | None = None
    on_finished: Callable[[], None] | None = None
    task_factory: Callable[..., Any] | None = None
    last_error: str | None = None
    last_finished: float | None = None
    last_success: float | None = None


class AppCoordinator:
    """Universal per-key shock absorber between background work and the UI.

    Dependency-composed: the caller injects how work runs (``runner``) and
    how results reach the UI thread (``deliver``), so this coordinator never
    owns threading, widgets, or delivery queues itself.

    In the game editor this coordinates:
    - project loading / scene saving / asset operations
    - background asset scans
    - editor metadata work
    - game/runtime launching

    Threading contract: ``run``/``begin``/``finish``/``cancel`` are called on
    the main thread; only each run's ``cancel_event`` crosses threads;
    ``deliver`` must be thread-safe and schedule callbacks on the UI thread.
    """

    def __init__(
        self,
        *,
        runner: Callable[[Callable[[], None]], Any] | None = None,
        deliver: Callable[[Callable[[], None]], None] | None = None,
        on_activity: Callable[[], None] | None = None,
        deliver_progress: Callable[[str, Callable[[], None]], None] | None = None,
        max_workers: int = 8,
        observer: ObservabilityWatcher | None = None,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._executor = None if runner is not None else ThreadPoolExecutor(max_workers=max_workers)
        self._runner = runner or self._submit_default
        self._deliver = deliver or (lambda callback: callback())
        self._on_activity = on_activity
        self._deliver_progress = deliver_progress or (
            lambda _key, callback: self._deliver(callback)
        )
        self._observer = observer
        self._states: dict[str, AppRunState] = {}
        self._generation_counter = 0
        self._coalesced_generations: dict[str, int] = {}
        self._coalesced_callbacks: dict[str, Callable[[], None]] = {}
        self._coalesced_pending: set[str] = set()
        self._deferred_triggers: dict[str, Callable[[], None]] = {}
        self._closed = False

    def _submit_default(self, worker: Callable[[], None]) -> Future[Any]:
        if self._executor is None:
            raise RuntimeError("default worker executor is unavailable")
        return self._executor.submit(worker)

    def state(self, key: str) -> AppRunState:
        return self._states.setdefault(key, AppRunState())

    def diagnostic_states(self) -> tuple[tuple[str, AppRunState], ...]:
        return tuple(self._states.items())

    @property
    def has_pending_work(self) -> bool:
        return any(state.in_flight for state in self._states.values())

    def begin(self, key: str) -> tuple[int, bool]:
        state = self.state(key)
        if state.in_flight:
            state.rerun_requested = True
            self._record_observer_event(key, "coalesced")
            return state.generation, False
        generation = self._claim_run(state)
        return generation, True

    def _claim_run(self, state: AppRunState) -> int:
        state.in_flight = True
        # Keep completion tokens unique across keys and cleared state recreation.
        self._generation_counter += 1
        state.generation = self._generation_counter
        state.rerun_requested = False
        state.cancelled = False
        state.cancel_event = threading.Event()
        return state.generation

    def run(
        self,
        key: str,
        task_factory: Callable[[threading.Event, Callable[[str], None]], Any],
        *,
        on_result: Callable[[str, Any], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
        on_progress: Callable[[str, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        cache_policy: CachePolicy = CachePolicy.NONE,
    ) -> int | None:
        if self._closed:
            raise RuntimeError("AppCoordinator is shut down")
        state = self.state(key)
        if state.in_flight:
            state.rerun_requested = True
            self._record_observer_event(key, "coalesced")
            if on_result is not None:
                state.on_result = on_result
            if on_error is not None:
                state.on_error = on_error
            if on_progress is not None:
                state.on_progress = on_progress
            state.on_finished = on_finished
            state.task_factory = task_factory
            return None
        if on_result is not None:
            state.on_result = on_result
        if on_error is not None:
            state.on_error = on_error
        if on_progress is not None:
            state.on_progress = on_progress
        state.on_finished = on_finished
        state.task_factory = task_factory
        if cache_policy is CachePolicy.STALE_WHILE_REFRESH:
            cached = state.last_result
            if cached is not None and on_result is not None:
                self.record_cache_hit(key)
                self._deliver(lambda: self._safe_invoke(on_result, key, cached))
        return self._start_run(key, state)

    def _start_run(self, key: str, state: AppRunState) -> int:
        generation = self._claim_run(state)
        cancel_event = state.cancel_event
        task_factory = state.task_factory
        token = self._begin_observation(key)
        observer = self._observer

        def emit_progress(message: str) -> None:
            self._deliver_progress(
                key,
                lambda: self._invoke_progress(key, generation, state, message),
            )

        def worker() -> None:
            try:
                result = task_factory(cancel_event, emit_progress)  # type: ignore[misc]
            except Exception as error:  # noqa: BLE001
                message = str(error)
                if token is not None and observer is not None:
                    self._finish_observation(
                        observer,
                        token,
                        outcome="failure",
                        detail=type(error).__name__,
                    )
                self._deliver(
                    lambda: self._complete_run(
                        key,
                        generation,
                        run_state=state,
                        error=message,
                    )
                )
            else:
                if token is not None and observer is not None:
                    self._finish_observation(
                        observer,
                        token,
                        outcome="cancelled"
                        if cancel_event is not None and cancel_event.is_set()
                        else "success",
                    )
                self._deliver(
                    lambda: self._complete_run(
                        key,
                        generation,
                        run_state=state,
                        result=result,
                    )
                )

        self._note_activity()
        try:
            submitted = self._runner(worker)
            if isinstance(submitted, Future):
                state.future = submitted
        except Exception as error:  # noqa: BLE001
            message = str(error)
            if token is not None and observer is not None:
                self._finish_observation(
                    observer,
                    token,
                    outcome="failure",
                    detail=type(error).__name__,
                )
            LOGGER.warning("Could not start operation %r: %s", key, message)
            self._deliver(
                lambda: self._complete_run(
                    key,
                    generation,
                    run_state=state,
                    error=message,
                )
            )
        return generation

    def _note_activity(self) -> None:
        if self._on_activity is not None:
            with contextlib.suppress(Exception):
                self._on_activity()

    def _record_observer_event(self, key: str, event: EventKind) -> None:
        if self._observer is not None:
            with contextlib.suppress(Exception):
                self._observer.record_event(f"app:{key}", event)

    def _begin_observation(self, key: str) -> ObservationToken | None:
        if self._observer is None:
            return None
        with contextlib.suppress(Exception):
            return self._observer.begin(f"app:{key}")
        # Observer target validation must not strand a run before submission.
        return None

    @staticmethod
    def _finish_observation(
        observer: ObservabilityWatcher,
        token: ObservationToken,
        *,
        outcome: Outcome,
        detail: str | None = None,
    ) -> None:
        with contextlib.suppress(Exception):
            observer.finish(token, outcome=outcome, detail=detail)
        # Reset or a faulty optional observer must not lose task completion.

    def _invoke_progress(
        self,
        key: str,
        generation: int,
        run_state: AppRunState,
        message: str,
    ) -> None:
        state = self._states.get(key)
        if state is not run_state or generation != run_state.generation or run_state.cancelled:
            return
        self._safe_invoke(run_state.on_progress, key, message)

    def _settle_run(self, state: AppRunState) -> bool:
        state.in_flight = False
        state.cancel_event = None
        state.future = None
        rerun_requested = state.rerun_requested
        state.rerun_requested = False
        return rerun_requested

    def _complete_run(
        self,
        key: str,
        generation: int,
        *,
        run_state: AppRunState,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        state = self._states.get(key)
        if state is not run_state or generation != run_state.generation or not run_state.in_flight:
            self._record_observer_event(key, "stale")
            return
        rerun_requested = self._settle_run(run_state)
        if run_state.cancelled:
            self._invoke_finished(key, run_state)
            if rerun_requested:
                self._replay(key, run_state)
            return
        if error is None:
            run_state.last_result = result
            run_state.last_success = time.time()
            run_state.last_error = None
            self._notify_subscribers(run_state, key, result)
            self._safe_invoke(run_state.on_result, key, result)
        else:
            run_state.last_error = error[:160]
            run_state.last_finished = time.time()
            self._notify_subscribers(run_state, key, None)
            self._safe_invoke(run_state.on_error, key, error)
        self._invoke_finished(key, run_state)
        if rerun_requested:
            self._replay(key, run_state)

    @staticmethod
    def _invoke_finished(key: str, state: AppRunState) -> None:
        if state.on_finished is None:
            return
        try:
            state.on_finished()
        except Exception as finalizer_error:  # noqa: BLE001
            LOGGER.warning("Operation %r finalizer failed: %s", key, finalizer_error)

    def _replay(self, key: str, state: AppRunState) -> None:
        if state.task_factory is not None:
            self._start_run(key, state)

    def _safe_invoke(
        self,
        handler: Callable[..., None] | None,
        key: str,
        payload: Any,
    ) -> None:
        if handler is None:
            return
        try:
            handler(key, payload)
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("Operation %r callback failed: %s", key, error)

    def _notify_subscribers(
        self,
        state: AppRunState,
        key: str,
        result: Any | None,
    ) -> None:
        subscribers = state.subscribers or []
        state.subscribers = None
        for callback in subscribers:
            try:
                callback(key, result)
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("Operation %r subscriber failed: %s", key, error)

    def finish(
        self,
        key: str,
        generation: int,
        result: Any | None = None,
    ) -> tuple[bool, bool]:
        state = self._states.get(key)
        if state is None or generation != state.generation or not state.in_flight:
            self._record_observer_event(key, "stale")
            return False, False
        rerun_requested = self._settle_run(state)
        if state.cancelled:
            return False, rerun_requested
        if result is not None:
            state.last_result = result
            state.last_success = time.time()
            state.last_error = None
        else:
            state.last_error = "operation did not produce a result"
            state.last_finished = time.time()
        self._notify_subscribers(state, key, result)
        return True, rerun_requested

    def cancel(self, key: str, cancellation_message: str | None = None) -> None:
        state = self._states.get(key)
        self._deferred_triggers.pop(key, None)
        if state is None:
            return
        already_cancelled = state.cancelled
        state.cancelled = True
        state.rerun_requested = False
        if state.cancel_event is not None:
            state.cancel_event.set()
        if state.future is not None:
            cancelled_before_start = state.future.cancel()
            state.future = None
            if cancelled_before_start:
                self._deliver(
                    lambda: self._complete_run(
                        key,
                        state.generation,
                        run_state=state,
                        error=cancellation_message,
                    )
                )
        if not already_cancelled:
            self._notify_subscribers(state, key, None)
        if (
            not already_cancelled
            and cancellation_message is not None
            and state.on_error is not None
        ):
            handler = state.on_error
            self._deliver(lambda: self._safe_invoke(handler, key, cancellation_message))

    def cancel_all(self, cancellation_message: str | None = None) -> None:
        for key in tuple(self._states):
            self.cancel(key, cancellation_message)

    def shutdown(self) -> None:
        self._closed = True
        for key, state in tuple(self._states.items()):
            if state.in_flight:
                self.cancel(key)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def in_flight(self, key: str) -> bool:
        state = self._states.get(key)
        return state.in_flight if state is not None else False

    def generation(self, key: str) -> int:
        state = self._states.get(key)
        return state.generation if state is not None else 0

    def last_result(self, key: str) -> Any | None:
        state = self._states.get(key)
        return state.last_result if state is not None else None

    def record_cache_hit(self, key: str) -> None:
        self._record_observer_event(key, "cache_hit")

    def store(self, key: str, result: Any) -> None:
        self.state(key).last_result = result

    def subscribe(
        self,
        key: str,
        callback: Callable[[str, Any | None], None],
    ) -> None:
        state = self.state(key)
        if state.subscribers is None:
            state.subscribers = []
        state.subscribers.append(callback)

    def unsubscribe(
        self,
        key: str,
        callback: Callable[[str, Any | None], None],
    ) -> None:
        state = self._states.get(key)
        if state is None or not state.subscribers:
            return
        state.subscribers = [item for item in state.subscribers if item != callback]

    def clear(self, key: str) -> None:
        self._states.pop(key, None)
        if key in self._coalesced_generations:
            self._coalesced_generations[key] += 1
        self._coalesced_callbacks.pop(key, None)
        self._coalesced_pending.discard(key)
        self._deferred_triggers.pop(key, None)

    def post(self, callback: Callable[[], None]) -> None:
        """Deliver one callback onto the UI thread and keep the poll alive."""
        self._note_activity()
        self._deliver(callback)

    def post_coalesced(self, key: str, callback: Callable[[], None]) -> None:
        """Schedule at most one pending callback for ``key``."""
        self._note_activity()
        self._coalesced_callbacks[key] = callback
        if key in self._coalesced_pending:
            return

        generation = self._coalesced_generations.get(key, 0) + 1
        self._coalesced_generations[key] = generation
        self._coalesced_pending.add(key)

        def deliver() -> None:
            if self._coalesced_generations.get(key) != generation:
                self._coalesced_pending.discard(key)
                return
            self._coalesced_pending.discard(key)
            current = self._coalesced_callbacks.pop(key, None)
            if current is None:
                return
            current()

        self._deliver(deliver)

    def defer(self, key: str, trigger: Callable[[], None]) -> None:
        self._deferred_triggers[key] = trigger

    def flush_deferred(self, key: str) -> None:
        trigger = self._deferred_triggers.pop(key, None)
        if trigger is not None:
            trigger()
