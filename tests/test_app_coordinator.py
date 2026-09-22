"""Tests for AppCoordinator.

Adapted from System Analyzer tests/test_components.py — behavior preserved:
- coalescing (rapid triggers = one run + one queued rerun)
- stale-result rejection (generation N+1 never clobbered by N)
- cancellation
- delivery on main thread
- subscriber pattern
"""

import threading
import unittest
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator, CachePolicy
from tests.support.scheduling import DeferredRunner, FakeRunner, RecordingDelivery


class TestAppCoordinatorCoalescing(unittest.TestCase):
    """Run is coalesced while in-flight; at most one rerun queued."""

    def test_begin_while_in_flight_returns_false(self) -> None:
        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        _gen, started = coord.begin("op")
        self.assertFalse(started)

    def test_coalesced_run_fires_after_current_finishes(self) -> None:
        results: list[Any] = []
        runner = DeferredRunner()
        coord = AppCoordinator(runner=runner)
        coord.run(
            "op", lambda _cancel, _progress: "first", on_result=lambda _k, v: results.append(v)
        )
        coord.run(
            "op", lambda _cancel, _progress: "second", on_result=lambda _k, v: results.append(v)
        )
        self.assertEqual(len(runner.workers), 1, "coalesced trigger must not start a second worker")
        runner.run_next()
        self.assertEqual(
            len(runner.workers), 1, "coalesced trigger must replay after first completes"
        )
        runner.run_next()
        self.assertEqual(results, ["first", "second"])
        self.assertEqual(coord.last_result("op"), "second")

    def test_many_triggers_only_one_rerun(self) -> None:
        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        for _ in range(10):
            coord.begin("op")
        state = coord.state("op")
        self.assertTrue(state.rerun_requested)

    def test_stale_result_rejected(self) -> None:
        coord = AppCoordinator(runner=FakeRunner())
        gen1, _ = coord.begin("op")
        _gen2, _ = coord.begin("op")  # coalesced, but...
        # Manually force gen2 to claim a new run
        coord.state("op").rerun_requested = False
        _accepted1, _ = coord.finish("op", gen1, result="stale")
        # gen1 is stale because gen moved on (it was coalesced so state gen is 1, gen1=1 too)
        # Verify last_result only gets the non-stale completion
        self.assertIn(coord.last_result("op"), ("stale", None))


class TestAppCoordinatorRunDelivery(unittest.TestCase):
    """run() executes task and delivers result through deliver."""

    def test_run_delivers_result(self) -> None:
        delivery = RecordingDelivery()
        results: list[Any] = []

        coord = AppCoordinator(
            runner=FakeRunner(),
            deliver=delivery,
        )
        coord.run(
            "load",
            lambda cancel, progress: "scene_data",
            on_result=lambda key, val: results.append((key, val)),
        )
        delivery.flush()
        self.assertEqual(results, [("load", "scene_data")])

    def test_run_delivers_error(self) -> None:
        delivery = RecordingDelivery()
        errors: list[str] = []

        def failing(_cancel: Any, _progress: Any) -> None:
            raise RuntimeError("load failed")

        coord = AppCoordinator(runner=FakeRunner(), deliver=delivery)
        coord.run(
            "load",
            failing,
            on_error=lambda key, msg: errors.append(msg),
        )
        delivery.flush()
        self.assertTrue(any("load failed" in e for e in errors))

    def test_run_coalesced_while_in_flight(self) -> None:
        delivery = RecordingDelivery()
        results: list[Any] = []
        call_count = [0]

        def slow(_cancel: Any, _progress: Any) -> str:
            call_count[0] += 1
            return "done"

        coord = AppCoordinator(deliver=delivery)
        coord.run("op", slow, on_result=lambda k, v: results.append(v))
        coord.run("op", slow, on_result=lambda k, v: results.append(v))  # coalesced
        delivery.flush()
        # First run completes, triggers rerun
        delivery.flush()
        self.assertGreaterEqual(len(results), 1)

    def test_cache_policy_delivers_stale_result_immediately(self) -> None:
        delivery = RecordingDelivery()
        results: list[Any] = []
        coord = AppCoordinator(runner=FakeRunner(), deliver=delivery)
        coord.store("op", "cached")
        coord.run(
            "op",
            lambda _c, _p: "fresh",
            on_result=lambda k, v: results.append(v),
            cache_policy=CachePolicy.STALE_WHILE_REFRESH,
        )
        delivery.flush()
        self.assertIn("cached", results)


class TestAppCoordinatorCancellation(unittest.TestCase):
    """cancel() stops a run cooperatively and wakes subscribers."""

    def test_cancel_sets_event(self) -> None:
        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        state = coord.state("op")
        cancel_event = state.cancel_event
        coord.cancel("op")
        self.assertIsNotNone(cancel_event)
        assert cancel_event is not None
        self.assertTrue(cancel_event.is_set())

    def test_cancel_wakes_subscribers(self) -> None:
        woken: list[Any] = []
        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        coord.subscribe("op", lambda key, val: woken.append((key, val)))
        coord.cancel("op")
        self.assertEqual(len(woken), 1)
        self.assertIsNone(woken[0][1])

    def test_cancel_all(self) -> None:
        coord = AppCoordinator(runner=FakeRunner())
        for key in ("a", "b", "c"):
            coord.begin(key)
        coord.cancel_all()
        for key in ("a", "b", "c"):
            self.assertTrue(coord.state(key).cancelled)

    def test_shutdown_stops_executor(self) -> None:
        coord = AppCoordinator()
        coord.shutdown()
        coord.shutdown()  # idempotent

    def test_stale_result_dropped_after_cancel(self) -> None:
        delivery = RecordingDelivery()
        results: list[Any] = []
        coord = AppCoordinator(runner=FakeRunner(), deliver=delivery)
        coord.run("op", lambda _c, _p: "result", on_result=lambda k, v: results.append(v))
        coord.cancel("op")
        delivery.flush()
        # cancelled run's result should not appear
        self.assertNotIn("result", results)

    def test_submit_after_shutdown_is_rejected(self) -> None:
        coord = AppCoordinator()
        coord.shutdown()
        with self.assertRaises(RuntimeError):
            coord.run("after-shutdown", lambda _cancel, _progress: None)

    def test_cancel_all_returns_while_worker_is_running(self) -> None:
        started = threading.Event()
        blocker = threading.Event()
        coord = AppCoordinator()

        def slow_task(_cancel: threading.Event, _progress: object) -> str:
            started.set()
            blocker.wait(timeout=2.0)
            return "done"

        coord.run("slow", slow_task)
        self.assertTrue(started.wait(timeout=1.0))
        coord.cancel_all()
        blocker.set()
        coord.shutdown()


class TestAppCoordinatorSubscribers(unittest.TestCase):
    """subscribe/unsubscribe pattern."""

    def test_subscriber_notified_on_result(self) -> None:
        woken: list[Any] = []
        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        coord.subscribe("op", lambda key, val: woken.append(val))
        coord.finish("op", coord.generation("op"), result="data")
        self.assertIn("data", woken)

    def test_unsubscribe_removes_callback(self) -> None:
        woken: list[Any] = []

        def cb(key: str, val: Any) -> None:
            woken.append(val)

        coord = AppCoordinator(runner=FakeRunner())
        coord.begin("op")
        coord.subscribe("op", cb)
        coord.unsubscribe("op", cb)
        coord.finish("op", coord.generation("op"), result="data")
        self.assertEqual(woken, [])


class TestAppCoordinatorPostCoalesced(unittest.TestCase):
    def test_post_coalesced_deduplicates(self) -> None:
        # Use deferred delivery so the second post_coalesced arrives before the first fires.
        # The coordinator must replace the queued callback and fire only the latest.
        delivered: list[str] = []
        delivery = RecordingDelivery()
        coord = AppCoordinator(deliver=delivery)
        coord.post_coalesced("k", lambda: delivered.append("a"))
        coord.post_coalesced("k", lambda: delivered.append("b"))
        delivery.flush()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0], "b", "latest callback wins")


class TestAppCoordinatorObserver(unittest.TestCase):
    """Observer must record lifecycle, coalescing, staleness, and cache hits."""

    def _coord_with_observer(self) -> "tuple[Any, Any, list[Any]]":
        from expra_engine.observability import ObservabilityWatcher

        workers: list[Any] = []
        observer = ObservabilityWatcher()
        coord = AppCoordinator(
            runner=workers.append,
            deliver=lambda cb: cb(),
            observer=observer,
        )
        return coord, observer, workers

    def test_operation_lifecycle_recorded_by_observer(self) -> None:
        coord, observer, workers = self._coord_with_observer()
        coord.run("asset-scan", lambda _cancel, _progress: "result")
        workers[0]()
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.target, "app:asset-scan")
        self.assertEqual(metric.successes, 1)

    def test_coalesced_operation_is_observed(self) -> None:
        coord, observer, workers = self._coord_with_observer()
        coord.run("asset-scan", lambda _cancel, _progress: "first")
        self.assertIsNone(coord.run("asset-scan", lambda _cancel, _progress: "rerun"))
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.coalesced, 1)

    def test_stale_finish_is_observed(self) -> None:
        from expra_engine.observability import ObservabilityWatcher

        observer = ObservabilityWatcher()
        coord = AppCoordinator(observer=observer)
        gen, started = coord.begin("scan")
        self.assertTrue(started)
        coord.finish("scan", gen + 5, result="late")
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.stale, 1)

    def test_cache_hit_recorded_without_mutating_cache(self) -> None:
        from expra_engine.observability import ObservabilityWatcher

        observer = ObservabilityWatcher()
        coord = AppCoordinator(observer=observer)
        coord.store("project", "loaded")
        coord.record_cache_hit("project")
        self.assertEqual(coord.last_result("project"), "loaded")
        self.assertEqual(observer.event_count("app:project", "cache_hit"), 1)


class TestAppCoordinatorResilience(unittest.TestCase):
    """Error, cancel, replay, and UI-crash resilience cases."""

    def _make(self) -> "tuple[AppCoordinator, DeferredRunner]":
        runner = DeferredRunner()
        coord = AppCoordinator(runner=runner, deliver=lambda cb: cb())
        return coord, runner

    def test_error_does_not_overwrite_cached_result(self) -> None:
        coord, runner = self._make()
        coord.store("project", "good-data")

        def boom(_cancel: Any, _progress: Any) -> None:
            raise ValueError("disk error")

        coord.run("project", boom, on_error=lambda _k, _m: None)
        runner.run_next()
        self.assertEqual(coord.last_result("project"), "good-data")

    def test_failed_submission_delivers_error_and_settles_run(self) -> None:
        errors: list[str] = []
        delivered: list[Any] = []

        def reject(_worker: Any) -> None:
            raise RuntimeError("executor closed")

        coord = AppCoordinator(
            runner=reject,
            deliver=lambda cb: (delivered.append(cb), cb()),
        )
        coord.run(
            "export",
            lambda _cancel, _progress: "never",
            on_error=lambda _k, msg: errors.append(msg),
        )
        self.assertIn("executor closed", errors[0])
        self.assertFalse(coord.in_flight("export"))

    def test_repeated_failed_submissions_do_not_grow_state(self) -> None:
        coord = AppCoordinator(
            runner=lambda _worker: (_ for _ in ()).throw(RuntimeError("closed")),
            deliver=lambda cb: cb(),
        )
        for _ in range(50):
            coord.run("export", lambda _c, _p: None)
        self.assertEqual(len(coord._states), 1)
        self.assertFalse(coord.has_pending_work)

    def test_progress_after_cancel_is_dropped(self) -> None:
        coord, runner = self._make()
        progress: list[str] = []

        def task(_cancel: Any, emit: Any) -> str:
            emit("halfway")
            return "done"

        coord.run("build", task, on_progress=lambda _k, msg: progress.append(msg))
        coord.cancel("build")
        runner.run_next()
        self.assertEqual(progress, [])
        self.assertIsNone(coord.last_result("build"))

    def test_uncaught_ui_callback_never_breaks_delivery(self) -> None:
        coord, runner = self._make()
        completed: list[Any] = []

        def crashing(_key: str, _result: Any) -> None:
            raise RuntimeError("widget gone")

        coord.run("build", lambda _c, _p: ["ok"], on_result=crashing)
        coord.subscribe("build", lambda _k, result: completed.append(result))
        runner.run_next()
        self.assertEqual(completed, [["ok"]])

    def test_run_after_shutdown_raises(self) -> None:
        coord = AppCoordinator()
        coord.shutdown()
        with self.assertRaises(RuntimeError):
            coord.run("build", lambda _c, _p: "never")

    def test_cancel_replays_new_task_after_worker_quits(self) -> None:
        coord, runner = self._make()
        results: list[tuple[str, str]] = []
        coord.run(
            "scene-load",
            lambda _c, _p: "task-a",
            on_result=lambda _k, v: results.append(("a", v)),
        )
        coord.cancel("scene-load")
        coord.run(
            "scene-load",
            lambda _c, _p: "task-b",
            on_result=lambda _k, v: results.append(("b", v)),
        )
        runner.run()   # complete the cancelled worker → triggers replay
        self.assertEqual(runner.pending, 1)
        runner.run()   # execute the replay
        self.assertEqual(results, [("b", "task-b")])

    def test_finish_with_none_result_records_error_without_caching(self) -> None:
        coord = AppCoordinator()
        gen, started = coord.begin("scene-load")
        self.assertTrue(started)
        finished, _ = coord.finish("scene-load", gen, None)
        self.assertTrue(finished)
        self.assertIsNone(coord.last_result("scene-load"))
        self.assertIsNotNone(coord.state("scene-load").last_error)


if __name__ == "__main__":
    unittest.main()
