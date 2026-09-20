"""Tests for editor-side render target resolution."""

from __future__ import annotations

import unittest
from typing import Any

from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.editor.contributions import RenderTargetRegistry


class RenderTargetRegistryTests(unittest.TestCase):
    def test_registered_target_receives_intent(self) -> None:
        applied: list[Any] = []
        targets = RenderTargetRegistry()
        targets.register("panel", applied.append)

        targets.callback_for("panel")(RenderIntent(target="panel", payload="value"))

        self.assertEqual(applied[0].payload, "value")

    def test_unknown_target_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            RenderTargetRegistry().callback_for("missing")

    def test_replacement_invalidates_pending_old_callback(self) -> None:
        old: list[Any] = []
        new: list[Any] = []
        targets = RenderTargetRegistry()
        targets.register("panel", old.append)
        old_callback = targets.callback_for("panel")
        coordinator = UICoordinator()
        coordinator.begin_batch()
        coordinator.request(RenderIntent(target="panel"), old_callback)
        targets.register("panel", new.append, replace=True)
        coordinator.end_batch()

        self.assertEqual(old, [])
        self.assertEqual(new, [])

    def test_callback_failure_reaches_ui_coordinator_isolation(self) -> None:
        def failing(_intent: RenderIntent) -> None:
            raise RuntimeError("broken panel")

        targets = RenderTargetRegistry()
        targets.register("panel", failing)
        coordinator = UICoordinator()

        coordinator.request(RenderIntent(target="panel"), targets.callback_for("panel"))

        self.assertEqual(coordinator.render_failures, 1)


if __name__ == "__main__":
    unittest.main()
