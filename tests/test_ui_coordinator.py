"""Tests for UICoordinator (render coordinator).

Adapted from System Analyzer tests/test_render_coordinator.py — behavior preserved:
- stale-result rejection (generation N+1 wins over N)
- coalescing (same target, same generation merges)
- visibility gating
- batch mode
- shutdown clears pending
"""

import unittest
from typing import Any
from unittest.mock import patch

from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.observability import ObservabilityWatcher


class TestUICoordinatorStaleRejection(unittest.TestCase):
    """Stale render intents must never overwrite newer committed state."""

    def test_stale_generation_rejected(self) -> None:
        committed: list[Any] = []
        coord = UICoordinator()
        coord.invalidate("hierarchy", generation=5)

        intent = RenderIntent(target="hierarchy", generation=3)
        result = coord.request(intent, lambda i: committed.append(i))
        self.assertFalse(result)
        self.assertEqual(committed, [])

    def test_current_generation_accepted(self) -> None:
        committed: list[Any] = []
        coord = UICoordinator()
        coord.invalidate("hierarchy", generation=2)

        intent = RenderIntent(target="hierarchy", generation=2)
        coord.request(intent, lambda i: committed.append(i))
        self.assertEqual(len(committed), 1)

    def test_newer_generation_supersedes_pending(self) -> None:
        # Use begin_batch so intents are queued and not immediately flushed.
        # This lets invalidate(gen=2) make intent1 stale before any flush.
        applied: list[int] = []
        coord = UICoordinator()
        intent1 = RenderIntent(target="inspector", generation=1)
        intent2 = RenderIntent(target="inspector", generation=2)
        coord.begin_batch()
        coord.request(intent1, lambda i: applied.append(i.generation))
        coord.invalidate("inspector", generation=2)
        coord.request(intent2, lambda i: applied.append(i.generation))
        coord.end_batch()
        self.assertIn(2, applied)
        self.assertNotIn(1, applied)

    def test_owner_switch_rejects_stale_inspector_result(self) -> None:
        applied: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(
            RenderIntent(target="inspector", owner_id="entity-a"),
            lambda _intent: applied.append("entity-a"),
        )
        coord.invalidate("inspector", owner_id="entity-b")
        coord.request(
            RenderIntent(target="inspector", owner_id="entity-a"),
            lambda _intent: applied.append("stale"),
        )
        coord.request(
            RenderIntent(target="inspector", generation=1, owner_id="entity-b"),
            lambda _intent: applied.append("entity-b"),
        )
        coord.end_batch()
        self.assertEqual(applied, ["entity-b"])


class TestUICoordinatorCoalescing(unittest.TestCase):
    def test_same_target_coalesces(self) -> None:
        applied: list[Any] = []
        coord = UICoordinator()
        coord.begin_batch()
        for _ in range(5):
            intent = RenderIntent(target="viewport", generation=1)
            coord.request(intent, lambda i: applied.append(i))
        coord.end_batch()
        self.assertEqual(len(applied), 1)

    def test_different_targets_both_applied(self) -> None:
        applied: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(RenderIntent(target="hierarchy"), lambda i: applied.append("hierarchy"))
        coord.request(RenderIntent(target="inspector"), lambda i: applied.append("inspector"))
        coord.end_batch()
        self.assertIn("hierarchy", applied)
        self.assertIn("inspector", applied)


class TestUICoordinatorVisibility(unittest.TestCase):
    def test_invisible_target_queued_not_applied(self) -> None:
        applied: list[Any] = []
        coord = UICoordinator()
        coord.set_visible("inspector", False)
        coord.request(RenderIntent(target="inspector"), lambda i: applied.append(i))
        self.assertEqual(applied, [])

    def test_setting_visible_flushes_pending(self) -> None:
        applied: list[Any] = []
        coord = UICoordinator()
        coord.set_visible("inspector", False)
        coord.request(RenderIntent(target="inspector"), lambda i: applied.append(i))
        coord.set_visible("inspector", True)
        self.assertEqual(len(applied), 1)


class TestUICoordinatorShutdown(unittest.TestCase):
    def test_shutdown_clears_pending(self) -> None:
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(RenderIntent(target="console"), lambda i: None)
        coord.shutdown()
        self.assertEqual(coord.pending_count, 0)

    def test_request_after_shutdown_rejected(self) -> None:
        coord = UICoordinator()
        coord.shutdown()
        result = coord.request(RenderIntent(target="hierarchy"), lambda i: None)
        self.assertFalse(result)

    def test_late_scheduled_flush_after_shutdown_cannot_commit(self) -> None:
        scheduled: list[Any] = []

        def schedule(_delay: int, callback: Any) -> int:
            scheduled.append(callback)
            return len(scheduled)

        coord = UICoordinator(schedule=schedule)
        applied: list[str] = []
        coord.request(RenderIntent("panel"), lambda _intent: applied.append("panel"))
        coord.shutdown()
        scheduled[0]()

        self.assertEqual(applied, [])
        self.assertEqual(coord.pending_count, 0)

    def test_mutators_after_shutdown_do_not_recreate_target_state(self) -> None:
        coord = UICoordinator()
        coord.begin_batch()
        coord.shutdown()

        self.assertEqual(coord._batch_depth, 0)
        for index in range(10):
            target = f"late-{index}"
            coord.invalidate(target, generation=1, owner_id=target)
            coord.set_visible(target, False)
            coord.clear(target)

        self.assertEqual(coord._pending, {})
        self.assertEqual(coord._visible, {})
        self.assertEqual(coord._generations, {})
        self.assertEqual(coord._target_nodes, {})


class TestUICoordinatorBatchDepth(unittest.TestCase):
    def test_nested_batch_requires_matching_end(self) -> None:
        applied: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.begin_batch()
        coord.request(RenderIntent(target="toolbar"), lambda _intent: applied.append("done"))
        coord.end_batch()
        self.assertEqual(applied, [])
        coord.end_batch()
        self.assertEqual(applied, ["done"])

    def test_end_batch_without_begin_is_noop(self) -> None:
        UICoordinator().end_batch()

    def test_flush_clears_all_pending(self) -> None:
        applied: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(RenderIntent(target="a"), lambda _intent: applied.append("a"))
        coord.request(RenderIntent(target="b"), lambda _intent: applied.append("b"))
        coord.flush()
        self.assertEqual(set(applied), {"a", "b"})
        self.assertEqual(coord.pending_count, 0)


class TestUICoordinatorMetrics(unittest.TestCase):
    def test_metrics_track_requests_and_commits(self) -> None:
        coord = UICoordinator()
        for i in range(3):
            coord.request(RenderIntent(target="toolbar", generation=i + 1), lambda intent: None)
        self.assertGreaterEqual(coord.render_requests, 3)

    def test_stale_rejection_increments_counter(self) -> None:
        coord = UICoordinator()
        coord.invalidate("assets", generation=10)
        coord.request(RenderIntent(target="assets", generation=5), lambda i: None)
        self.assertGreaterEqual(coord.stale_rejections, 1)


class TestRenderIntentMerge(unittest.TestCase):
    def test_merge_takes_higher_generation(self) -> None:
        a = RenderIntent(target="t", generation=1, components=frozenset(["a"]))
        b = RenderIntent(target="t", generation=2, components=frozenset(["b"]))
        merged = a.merge(b)
        self.assertEqual(merged.generation, 2)
        self.assertIn("a", merged.components)
        self.assertIn("b", merged.components)

    def test_merge_different_targets_raises(self) -> None:
        a = RenderIntent(target="x")
        b = RenderIntent(target="y")
        with self.assertRaises(ValueError):
            a.merge(b)


class TestUICoordinatorObserver(unittest.TestCase):
    """Observer must record commits, coalesced, stale, and rejected events."""

    def test_commit_is_recorded_by_shared_observer(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)
        coord.request(RenderIntent("hierarchy"), lambda _: None)
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.target, "ui:render:hierarchy")
        self.assertEqual(metric.successes, 1)

    def test_coalesced_stale_and_rejected_events_all_observed(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)
        # Coalesced: two requests inside a batch → one commit
        coord.begin_batch()
        coord.request(RenderIntent("viewport"), lambda _: None)
        coord.request(RenderIntent("viewport"), lambda _: None)
        coord.end_batch()
        # Stale: generation too old
        coord.invalidate("viewport", 10)
        coord.request(RenderIntent("viewport", generation=2), lambda _: None)
        # Rejected: after shutdown
        coord.shutdown()
        coord.request(RenderIntent("viewport"), lambda _: None)

        metric = observer.snapshot().metrics[0]
        self.assertGreaterEqual(metric.coalesced, 1)
        self.assertGreaterEqual(metric.stale, 1)
        self.assertGreaterEqual(metric.rejected, 1)

    def test_observer_record_failure_does_not_block_render_commit(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)
        applied: list[str] = []

        with patch.object(observer, "record_event", side_effect=RuntimeError("observer failed")):
            accepted = coord.request(RenderIntent("panel"), lambda _intent: applied.append("panel"))

        self.assertTrue(accepted)
        self.assertEqual(applied, ["panel"])
        self.assertEqual(coord.pending_count, 0)

    def test_observer_begin_failure_does_not_drop_pending_render(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)
        applied: list[str] = []

        with patch.object(observer, "begin", side_effect=RuntimeError("observer failed")):
            accepted = coord.request(RenderIntent("panel"), lambda _intent: applied.append("panel"))

        self.assertTrue(accepted)
        self.assertEqual(applied, ["panel"])
        self.assertEqual(coord.pending_count, 0)

    def test_observer_finish_failure_does_not_escape_after_commit(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)
        applied: list[str] = []

        with patch.object(observer, "finish", side_effect=RuntimeError("observer failed")):
            accepted = coord.request(RenderIntent("panel"), lambda _intent: applied.append("panel"))

        self.assertTrue(accepted)
        self.assertEqual(applied, ["panel"])
        self.assertEqual(coord.pending_count, 0)

    def test_observer_rejecting_long_target_does_not_reject_render(self) -> None:
        coord = UICoordinator(observer=ObservabilityWatcher())
        target = "panel-" + "x" * 150
        applied: list[str] = []

        self.assertTrue(
            coord.request(RenderIntent(target), lambda intent: applied.append(intent.target))
        )

        self.assertEqual(applied, [target])
        self.assertEqual(coord.pending_count, 0)

    def test_metric_queries_fail_soft_when_observer_is_unavailable(self) -> None:
        observer = ObservabilityWatcher()
        coord = UICoordinator(observer=observer)

        with patch.object(observer, "event_total", side_effect=RuntimeError("observer failed")):
            self.assertEqual(coord.render_requests, 0)


class TestUICoordinatorFieldMerge(unittest.TestCase):
    """Coalescing must union components, OR layout_changed, and take max priority."""

    def test_merge_unions_components_layout_and_priority(self) -> None:
        received: list[RenderIntent] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(
            RenderIntent(
                target="inspector",
                payload="first",
                payload_set=True,
                components=frozenset({"transform"}),
                priority=1,
            ),
            received.append,
        )
        coord.request(
            RenderIntent(
                target="inspector",
                payload="second",
                payload_set=True,
                components=frozenset({"sprite"}),
                layout_changed=True,
                priority=3,
            ),
            received.append,
        )
        coord.end_batch()

        self.assertEqual(len(received), 1)
        merged = received[0]
        self.assertEqual(merged.payload, "second")
        self.assertEqual(merged.components, frozenset({"transform", "sprite"}))
        self.assertTrue(merged.layout_changed)
        self.assertEqual(merged.priority, 3)


class TestUICoordinatorPendingBounded(unittest.TestCase):
    """100 requests for the same target must stay bounded to 1 pending + 1 commit."""

    def test_hundred_requests_produce_one_commit(self) -> None:
        received: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        for i in range(100):
            coord.request(
                RenderIntent(target="console", payload=f"line-{i}", payload_set=True),
                lambda intent: received.append(str(intent.payload)),
            )
        self.assertEqual(coord.pending_count, 1)
        coord.end_batch()
        self.assertEqual(received, ["line-99"])
        self.assertEqual(coord.render_commits, 1)


class TestUICoordinatorReentrancy(unittest.TestCase):
    """A render callback that queues another request must be committed in the same flush."""

    def test_request_inside_apply_callback_is_committed(self) -> None:
        received: list[str] = []
        coord = UICoordinator()

        def apply_hierarchy(_intent: RenderIntent) -> None:
            received.append("hierarchy")
            coord.request(
                RenderIntent(target="status", payload="updated", payload_set=True),
                lambda intent: received.append(str(intent.payload)),
            )

        coord.begin_batch()
        coord.request(RenderIntent(target="hierarchy"), apply_hierarchy)
        coord.end_batch()

        self.assertEqual(received, ["hierarchy", "updated"])
        self.assertEqual(coord.pending_count, 0)
        self.assertEqual(coord.render_commits, 2)


class TestUICoordinatorNonePayload(unittest.TestCase):
    """Explicit None payload with payload_set=True must clear a prior payload."""

    def test_none_payload_clears_previous(self) -> None:
        received: list[RenderIntent] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(
            RenderIntent(target="inspector", payload="entity", payload_set=True),
            received.append,
        )
        coord.request(
            RenderIntent(target="inspector", payload=None, payload_set=True),
            received.append,
        )
        coord.end_batch()
        self.assertEqual(len(received), 1)
        self.assertIsNone(received[0].payload)
        self.assertTrue(received[0].payload_set)


class TestUICoordinatorMetricsExtended(unittest.TestCase):
    """pending_peak, commit duration, failure counter, and thread identity."""

    def test_pending_peak_and_commit_duration_tracked(self) -> None:
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(RenderIntent(target="assets"), lambda _: None)
        coord.end_batch()
        self.assertEqual(coord.pending_peak, 1)
        self.assertGreaterEqual(coord.last_commit_seconds, 0.0)

    def test_failed_commit_increments_failure_counter(self) -> None:
        coord = UICoordinator()

        def bad_apply(_intent: RenderIntent) -> None:
            raise RuntimeError("widget gone")

        coord.request(RenderIntent(target="viewport"), bad_apply)
        self.assertEqual(coord.render_failures, 1)

    def test_failed_commit_is_not_counted_as_successful_commit(self) -> None:
        coord = UICoordinator()

        def bad_apply(_intent: RenderIntent) -> None:
            raise RuntimeError("widget gone")

        coord.request(RenderIntent(target="viewport"), bad_apply)

        self.assertEqual(coord.render_failures, 1)
        self.assertEqual(coord.render_commits, 0)

    def test_failed_commit_log_bounds_target_and_error_detail(self) -> None:
        coord = UICoordinator()

        def bad_apply(_intent: RenderIntent) -> None:
            raise RuntimeError("detail " * 10000)

        with self.assertLogs("expra_engine.coordinators.ui_coordinator", level="WARNING") as logs:
            coord.request(RenderIntent(target="panel-" + "x" * 1000), bad_apply)

        self.assertLessEqual(len(logs.output[0]), 400)

    def test_commit_runs_on_requesting_thread(self) -> None:
        import threading

        coord = UICoordinator()
        committed_on: list[Any] = []
        coord.request(
            RenderIntent(target="toolbar"),
            lambda _intent: committed_on.append(threading.current_thread()),
        )
        self.assertEqual(committed_on, [threading.current_thread()])


class TestUICoordinatorPriorityFlush(unittest.TestCase):
    """Higher-priority targets must be committed before lower-priority ones."""

    def test_flush_commits_by_descending_priority(self) -> None:
        committed: list[str] = []
        coord = UICoordinator()
        coord.begin_batch()
        coord.request(
            RenderIntent(target="console", priority=1),
            lambda _: committed.append("console"),
        )
        coord.request(
            RenderIntent(target="status", priority=5),
            lambda _: committed.append("status"),
        )
        coord.request(
            RenderIntent(target="toolbar", priority=3),
            lambda _: committed.append("toolbar"),
        )
        coord.end_batch()
        self.assertEqual(committed, ["status", "toolbar", "console"])


class TestUICoordinatorTransitions(unittest.TestCase):
    """schedule_transition / cancel_transition must manage named timer slots."""

    def _make(self) -> "tuple[UICoordinator, list[tuple[int, Any]], list[Any]]":
        scheduled: list[tuple[int, Any]] = []
        cancelled: list[Any] = []
        timer_id = 0

        def fake_schedule(delay: int, callback: Any) -> int:
            nonlocal timer_id
            timer_id += 1
            scheduled.append((delay, callback))
            return timer_id

        def fake_cancel(identifier: Any) -> bool:
            cancelled.append(identifier)
            return True

        coord = UICoordinator(schedule=fake_schedule, cancel=fake_cancel)
        return coord, scheduled, cancelled

    def test_schedule_transition_fires_after_delay(self) -> None:
        coord, scheduled, _ = self._make()
        applied: list[str] = []
        coord.schedule_transition("play-start", 300, lambda: applied.append("done"))
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][0], 300)
        self.assertEqual(applied, [])
        scheduled[0][1]()  # fire the timer
        self.assertEqual(applied, ["done"])

    def test_schedule_transition_supersedes_pending(self) -> None:
        coord, scheduled, cancelled = self._make()
        applied: list[str] = []
        coord.schedule_transition("status", 200, lambda: applied.append("first"))
        coord.schedule_transition("status", 200, lambda: applied.append("second"))
        self.assertEqual(len(cancelled), 1, "first timer must be cancelled")
        scheduled[1][1]()  # fire only the second
        self.assertEqual(applied, ["second"])

    def test_schedule_different_names_are_independent(self) -> None:
        coord, scheduled, cancelled = self._make()
        coord.schedule_transition("play", 200, lambda: None)
        coord.schedule_transition("scan", 100, lambda: None)
        self.assertEqual(len(cancelled), 0, "different names must not cancel each other")
        self.assertEqual(len(scheduled), 2)

    def test_cancel_transition_cancels_the_timer(self) -> None:
        coord, _scheduled, cancelled = self._make()
        coord.schedule_transition("status", 200, lambda: None)
        coord.cancel_transition("status")
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0], 1)
        self.assertEqual(coord._transitions, {})

    def test_cancelled_transition_callback_cannot_fire_after_slot_release(self) -> None:
        coord, scheduled, _cancelled = self._make()
        applied: list[str] = []
        coord.schedule_transition("status", 200, lambda: applied.append("applied"))

        coord.cancel_transition("status")
        scheduled[0][1]()

        self.assertEqual(applied, [])
        self.assertEqual(coord._transitions, {})

    def test_cancel_transition_unknown_name_is_safe(self) -> None:
        coord, _, _ = self._make()
        coord.cancel_transition("nonexistent")  # must not raise

    def test_shutdown_cancels_all_pending_transitions(self) -> None:
        coord, _, cancelled = self._make()
        coord.schedule_transition("play", 200, lambda: None)
        coord.schedule_transition("scan", 100, lambda: None)
        coord.shutdown()
        self.assertEqual(len(cancelled), 2)

    def test_no_schedule_callable_means_transitions_are_noop(self) -> None:
        coord = UICoordinator()  # no schedule/cancel injected
        coord.schedule_transition("status", 200, lambda: None)  # must not raise
        coord.cancel_transition("status")  # must not raise
        coord.shutdown()  # must not raise

    def test_no_schedule_callable_does_not_retain_inert_transition(self) -> None:
        coord = UICoordinator()
        coord.schedule_transition("status", 200, lambda: self.fail("transition should be inert"))

        self.assertEqual(coord._transitions, {})

    def test_transition_registry_releases_completed_unique_names(self) -> None:
        coord, scheduled, _cancelled = self._make()

        for index in range(100):
            coord.schedule_transition(f"transition-{index}", 1, lambda: None)
            scheduled[-1][1]()

        self.assertEqual(coord._transitions, {})

    def test_transition_callback_failure_is_logged_and_releases_its_slot(self) -> None:
        coord, scheduled, _cancelled = self._make()

        def fail() -> None:
            raise RuntimeError("transition failed" * 1000)

        coord.schedule_transition("status", 1, fail)
        with self.assertLogs("expra_engine.coordinators.ui_coordinator", level="WARNING") as logs:
            scheduled[0][1]()

        self.assertLessEqual(len(logs.output[0]), 350)
        self.assertEqual(coord._transitions, {})

    def test_transition_schedule_partial_failure_does_not_retain_or_apply_callback(self) -> None:
        callbacks: list[Any] = []
        applied: list[str] = []

        def register_then_fail(_delay: int, callback: Any) -> int:
            callbacks.append(callback)
            raise RuntimeError("timer backend failed after registration")

        coord = UICoordinator(schedule=register_then_fail)
        with self.assertRaisesRegex(RuntimeError, "after registration"):
            coord.schedule_transition("status", 1, lambda: applied.append("applied"))

        callbacks[0]()

        self.assertEqual(applied, [])
        self.assertEqual(coord._transitions, {})

    def test_reentrant_transition_replacement_keeps_new_timer_until_it_fires(self) -> None:
        coord, scheduled, _cancelled = self._make()
        applied: list[str] = []

        def first() -> None:
            applied.append("first")
            coord.schedule_transition("status", 2, lambda: applied.append("second"))

        coord.schedule_transition("status", 1, first)
        scheduled[0][1]()
        self.assertIn("status", coord._transitions)

        scheduled[1][1]()

        self.assertEqual(applied, ["first", "second"])
        self.assertEqual(coord._transitions, {})

    def test_shutdown_is_terminal_for_transition_scheduling(self) -> None:
        coord, scheduled, _cancelled = self._make()
        coord.shutdown()

        coord.schedule_transition("late", 1, lambda: self.fail("late transition fired"))

        self.assertEqual(scheduled, [])

    def test_shutdown_continues_transition_cancellation_after_failure(self) -> None:
        scheduled: list[tuple[int, Any]] = []
        cancelled: list[Any] = []

        def schedule(delay: int, callback: Any) -> int:
            identifier = len(scheduled) + 1
            scheduled.append((identifier, callback))
            return identifier

        def cancel(identifier: Any) -> bool:
            cancelled.append(identifier)
            if identifier == 1:
                raise RuntimeError("scheduler is closing")
            return True

        coord = UICoordinator(schedule=schedule, cancel=cancel)
        applied: list[str] = []
        coord.schedule_transition("first", 1, lambda: applied.append("first"))
        coord.schedule_transition("second", 1, lambda: applied.append("second"))

        coord.shutdown()
        for _identifier, callback in scheduled:
            callback()

        self.assertEqual(cancelled, [1, 2])
        self.assertEqual(applied, [])
        self.assertEqual(coord._transitions, {})


class TestUICoordinatorFlushScheduling(unittest.TestCase):
    def test_synchronous_scheduler_does_not_leave_stale_flush_flag(self) -> None:
        applied: list[str] = []

        def schedule(_delay: int, callback: Any) -> object:
            callback()
            return object()

        coord = UICoordinator(schedule=schedule)
        coord.request(RenderIntent("first"), lambda _intent: applied.append("first"))
        coord.request(RenderIntent("second"), lambda _intent: applied.append("second"))

        self.assertEqual(applied, ["first", "second"])
        self.assertEqual(coord.pending_count, 0)

    def test_scheduler_exception_falls_back_to_synchronous_commit(self) -> None:
        applied: list[str] = []

        def schedule(_delay: int, _callback: Any) -> object:
            raise RuntimeError("event loop unavailable")

        coord = UICoordinator(schedule=schedule)
        accepted = coord.request(RenderIntent("panel"), lambda _intent: applied.append("panel"))

        self.assertTrue(accepted)
        self.assertEqual(applied, ["panel"])
        self.assertEqual(coord.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
