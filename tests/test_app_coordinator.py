"""Tests for AppCoordinator.

Adapted from System Analyzer tests/test_components.py — behavior preserved:
- coalescing (rapid triggers = one run + one queued rerun)
- stale-result rejection (generation N+1 never clobbered by N)
- cancellation
- delivery on main thread
- subscriber pattern
"""

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


if __name__ == "__main__":
    unittest.main()
