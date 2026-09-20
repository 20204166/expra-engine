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

from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator


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


if __name__ == "__main__":
    unittest.main()
