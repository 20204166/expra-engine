"""Deterministic scheduling fakes for coordinator and concurrency tests.

Adapted from System Analyzer tests/support/scheduling.py.

The deferred runner models the exact worker queue AppCoordinator consumes
without real threads. It is deliberately minimal — it records the scheduling
contract and lets tests step time explicitly.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any


class FakeClock:
    """Controllable monotonic clock for tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._time = start

    def __call__(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds


class DeferredRunner:
    """Queued worker runner that executes workers only when the test steps it.

    One fresh instance must be created per test: the queue is mutable state
    that must never leak between tests. ``run(index)`` steps one queued worker;
    the default ``index=0`` is FIFO, and an explicit index lets a test run a
    later worker first without real threads.
    """

    def __init__(self) -> None:
        self.workers: list[Callable[[], None]] = []

    def __call__(self, worker: Callable[[], None]) -> None:
        self.workers.append(worker)

    def run(self, index: int = 0) -> None:
        self.workers.pop(index)()

    def run_next(self) -> None:
        self.run(0)

    @property
    def pending(self) -> int:
        return len(self.workers)


class FakeRunner:
    """Synchronous task runner that executes tasks inline (no threads)."""

    def __call__(self, worker: Callable[[], None]) -> None:
        worker()


class ThreadSafeRunner:
    """Runner that executes in a real thread and waits for completion."""

    def __call__(self, worker: Callable[[], None]) -> None:
        done = threading.Event()
        error: list[BaseException] = []

        def run() -> None:
            try:
                worker()
            except Exception as exc:  # noqa: BLE001
                error.append(exc)
            finally:
                done.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        done.wait(timeout=5.0)
        if error:
            raise error[0]


class RecordingDelivery:
    """Records callbacks delivered to the UI thread for inspection in tests."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def flush(self) -> None:
        """Execute all queued callbacks."""
        pending = list(self._callbacks)
        self._callbacks.clear()
        for cb in pending:
            cb()

    @property
    def count(self) -> int:
        return len(self._callbacks)


class ManualExecutor(Executor):
    """Deterministic ``concurrent.futures.Executor`` fake for World streaming tests.

    Jobs queue on ``submit`` and only run when a test calls ``complete(index)``,
    letting tests control load ordering and interleave world-streaming ``update()``
    calls between worker completions. Matches real ``Executor`` semantics: a
    worker exception is captured on the ``Future`` (never raised out of
    ``complete``), and ``complete`` tolerates a future a test already drove to
    "running" directly (e.g. to simulate an in-flight load before cancelling it).
    """

    def __init__(self, max_workers: int) -> None:
        self.max_workers = max_workers
        self.jobs: list[tuple[Future[object], Callable[[], object]]] = []
        self.closed = False

    def submit(self, function: Callable[[], object]) -> Future[object]:
        future: Future[object] = Future()
        self.jobs.append((future, function))
        return future

    def complete(self, index: int = 0) -> None:
        future, function = self.jobs[index]
        if not future.running():
            future.set_running_or_notify_cancel()
        try:
            result = function()
        except Exception as error:  # noqa: BLE001 - propagate worker failures through the Future
            future.set_exception(error)
        else:
            future.set_result(result)

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        del wait
        self.closed = True
        if cancel_futures:
            for future, _ in self.jobs:
                future.cancel()


class FakeScheduler:
    """Records scheduled/cancelled callbacks for the ``schedule``/``cancel``
    callable-pair contract (``Callable[[int, Callable[[], None]], Any]`` /
    ``Callable[[Any], bool]``) that ``PendingTransition`` and ``UICoordinator``
    both accept for deterministic timer testing.
    """

    def __init__(self) -> None:
        self._scheduled: list[tuple[int, Callable[[], None]]] = []
        self._cancelled: list[Any] = []
        self._next_id = 0

    def schedule(self, delay: int, callback: Callable[[], None]) -> int:
        self._next_id += 1
        self._scheduled.append((delay, callback))
        return self._next_id

    def cancel(self, identifier: Any) -> bool:
        self._cancelled.append(identifier)
        return True

    def fire_last(self) -> None:
        if self._scheduled:
            _, callback = self._scheduled[-1]
            callback()


class ImmediateExecutor(Executor):
    """``concurrent.futures.Executor`` fake that runs submitted work synchronously.

    For World streaming tests that don't care about load ordering or timing and
    just want the loader to run inline on ``submit`` (no explicit ``complete()``
    step, unlike ``ManualExecutor``).
    """

    def submit(self, function: Callable[[], object]) -> Future[object]:
        future: Future[object] = Future()
        future.set_result(function())
        return future

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        del wait, cancel_futures
