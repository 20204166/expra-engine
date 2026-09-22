"""Tests for ButtonCoordinator.

Adapted from System Analyzer tests/test_action_coordinator.py — behavior preserved:
- register/dispatch
- enabled/disabled state
- widget binding
- duplicate registration guard
"""

import unittest
from typing import Any

from expra_engine.coordinators.button_coordinator import ButtonCoordinator


class FakeWidget:
    """Minimal widget double for ButtonCoordinator tests."""

    def __init__(self) -> None:
        self._state = "normal"
        self._command: Any = None
        self._exists = True

    def configure(self, **kwargs: Any) -> None:
        if "state" in kwargs:
            self._state = kwargs["state"]
        if "command" in kwargs:
            self._command = kwargs["command"]

    config = configure

    def winfo_exists(self) -> bool:
        return self._exists


class TestButtonCoordinatorRegister(unittest.TestCase):
    def test_register_and_dispatch(self) -> None:
        calls: list[str] = []
        coord = ButtonCoordinator()
        coord.register("new_scene", lambda: calls.append("new_scene"))
        result = coord.dispatch("new_scene")
        self.assertTrue(result)
        self.assertEqual(calls, ["new_scene"])

    def test_dispatch_unknown_id_returns_false(self) -> None:
        coord = ButtonCoordinator()
        self.assertFalse(coord.dispatch("unknown"))

    def test_dispatch_disabled_returns_false(self) -> None:
        calls: list[str] = []
        coord = ButtonCoordinator()
        coord.register("play", lambda: calls.append("play"))
        coord.set_enabled("play", False)
        result = coord.dispatch("play")
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_duplicate_registration_raises(self) -> None:
        coord = ButtonCoordinator()
        coord.register("save", lambda: None)
        with self.assertRaises(ValueError):
            coord.register("save", lambda: None)

    def test_replace_allowed(self) -> None:
        calls: list[str] = []
        coord = ButtonCoordinator()
        coord.register("save", lambda: calls.append("old"))
        coord.register("save", lambda: calls.append("new"), replace=True)
        coord.dispatch("save")
        self.assertEqual(calls, ["new"])

    def test_empty_action_id_raises(self) -> None:
        coord = ButtonCoordinator()
        with self.assertRaises(ValueError):
            coord.register("", lambda: None)


class TestButtonCoordinatorWidgetBinding(unittest.TestCase):
    def test_bind_applies_command(self) -> None:
        coord = ButtonCoordinator()
        coord.register("play", lambda: None)
        widget = FakeWidget()
        coord.bind(widget, "play")
        self.assertIsNotNone(widget._command)

    def test_bind_disabled_action_disables_widget(self) -> None:
        coord = ButtonCoordinator()
        coord.register("play", lambda: None, enabled=False)
        widget = FakeWidget()
        coord.bind(widget, "play")
        self.assertEqual(widget._state, "disabled")

    def test_set_enabled_updates_widget_state(self) -> None:
        coord = ButtonCoordinator()
        coord.register("play", lambda: None)
        widget = FakeWidget()
        coord.bind(widget, "play")
        coord.set_enabled("play", False)
        self.assertEqual(widget._state, "disabled")
        coord.set_enabled("play", True)
        self.assertEqual(widget._state, "normal")

    def test_dead_widget_removed_from_tracking(self) -> None:
        coord = ButtonCoordinator()
        coord.register("play", lambda: None)
        widget = FakeWidget()
        coord.bind(widget, "play")
        widget._exists = False
        coord.set_enabled("play", False)
        record = coord._actions["play"]
        self.assertNotIn(widget, record.widgets)

    def test_command_calls_dispatch(self) -> None:
        calls: list[str] = []
        coord = ButtonCoordinator()
        coord.register("stop", lambda: calls.append("stop"))
        cmd = coord.command("stop")
        cmd()
        self.assertEqual(calls, ["stop"])


class TestButtonCoordinatorUnregister(unittest.TestCase):
    def test_unregister_removes_action(self) -> None:
        coord = ButtonCoordinator()
        coord.register("op", lambda: None)
        coord.unregister("op")
        self.assertFalse(coord.dispatch("op"))

    def test_clear_prefix_removes_matching(self) -> None:
        coord = ButtonCoordinator()
        coord.register("entity:add", lambda: None)
        coord.register("entity:delete", lambda: None)
        coord.register("scene:save", lambda: None)
        coord.clear_prefix("entity:")
        self.assertFalse(coord.dispatch("entity:add"))
        self.assertFalse(coord.dispatch("entity:delete"))
        self.assertTrue(coord.dispatch("scene:save"))

    def test_registered_ids(self) -> None:
        coord = ButtonCoordinator()
        coord.register("a", lambda: None)
        coord.register("b", lambda: None)
        self.assertIn("a", coord.registered_ids())
        self.assertIn("b", coord.registered_ids())


class TestButtonCoordinatorObserver(unittest.TestCase):
    """Observer integration: dispatches and rejections must be recorded."""

    def _make(self) -> "tuple[ButtonCoordinator, Any]":
        from expra_engine.observability import ObservabilityWatcher

        observer = ObservabilityWatcher()
        coord = ButtonCoordinator(observer=observer)
        return coord, observer

    def test_dispatch_is_recorded_by_observer(self) -> None:
        coord, observer = self._make()
        coord.register("entity:add", lambda: None)
        coord.dispatch("entity:add")
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.target, "ui:action:entity:add")
        self.assertEqual(metric.successes, 1)

    def test_disabled_dispatch_is_observed_as_rejected(self) -> None:
        coord, observer = self._make()
        coord.register("entity:add", lambda: None, enabled=False)
        coord.dispatch("entity:add")
        metric = observer.snapshot().metrics[0]
        self.assertEqual(metric.rejected, 1)


class TestButtonCoordinatorTclError(unittest.TestCase):
    """Tk widget errors must never crash the coordinator; dead widgets are pruned."""

    def _tcl_widget(self, raises_on_config: bool = False) -> Any:
        """Return a fake widget whose config() either works or raises TclError."""
        import tkinter as tk

        class _W:
            def __init__(self) -> None:
                self._exists = True
                self.calls: list[Any] = []

            def winfo_exists(self) -> bool:
                return self._exists

            def config(self, **options: Any) -> None:
                if raises_on_config:
                    raise tk.TclError("invalid command name")
                self.calls.append(options)

            configure = config

        return _W()

    def test_replace_prunes_widget_that_fails_state_update(self) -> None:
        coord = ButtonCoordinator()
        widget = self._tcl_widget(raises_on_config=True)
        coord.register("scene:save", lambda: None)
        # Bind succeeds at first (widget exists); later a replace triggers state re-sync.
        # The TclError during the re-sync must drop the widget from tracking.
        coord._actions["scene:save"].widgets.append(widget)
        coord.register("scene:save", lambda: None, replace=True)
        self.assertEqual(coord._actions["scene:save"].widgets, [])

    def test_bind_unknown_action_raises_key_error(self) -> None:
        coord = ButtonCoordinator()
        widget = self._tcl_widget()
        with self.assertRaises(KeyError):
            coord.bind(widget, "nonexistent:action")

    def test_bind_tcl_error_drops_widget(self) -> None:
        coord = ButtonCoordinator()
        coord.register("entity:delete", lambda: None)
        widget = self._tcl_widget(raises_on_config=True)
        coord.bind(widget, "entity:delete")
        # Widget raised TclError during config() — must be dropped, not tracked.
        self.assertEqual(coord._actions["entity:delete"].widgets, [])
        # But the action itself must still be dispatchable.
        self.assertTrue(coord.dispatch("entity:delete"))


if __name__ == "__main__":
    unittest.main()
