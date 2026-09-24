"""Pure-logic tests for the retained editor panel router."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from expra_engine.coordinators.app_coordinator import AppCoordinator, CachePolicy
from expra_engine.observability import ObservabilityWatcher
from expra_engine.ui.navigation import PanelRouter, PanelSpec
from tests.support.scheduling import DeferredRunner


def _router(*keys: str) -> tuple[PanelRouter, dict[str, MagicMock]]:
    panels: dict[str, MagicMock] = {}

    def build(key: str) -> Callable[[Any], MagicMock]:
        def builder(_host: Any) -> MagicMock:
            panel = MagicMock()
            panels[key] = panel
            return panel

        return builder

    router = PanelRouter(MagicMock())
    for key in keys:
        router.register(PanelSpec(key, build(key)))
    return router, panels


class PanelRouterTests(unittest.TestCase):
    def test_register_and_show(self) -> None:
        router = PanelRouter(MagicMock())
        panel = MagicMock()
        router.register(PanelSpec("scene", lambda _host: panel))

        shown = router.show("scene")

        self.assertIs(shown, panel)
        self.assertEqual(router.active_key, "scene")
        panel.pack.assert_called_once_with(fill="both", expand=True)

    def test_show_unknown_raises_key_error(self) -> None:
        router = PanelRouter(MagicMock())

        with self.assertRaises(KeyError):
            router.show("nonexistent")
        self.assertIsNone(router.active_key)

    def test_registered_keys(self) -> None:
        router = PanelRouter(MagicMock())
        router.register(PanelSpec("a", lambda _host: MagicMock()))
        router.register(PanelSpec("b", lambda _host: MagicMock()))

        self.assertEqual(router.registered_keys, ("a", "b"))

    def test_get_panel_returns_registered_panel(self) -> None:
        router = PanelRouter(MagicMock())
        panel = MagicMock()
        router.register(PanelSpec("x", lambda _host: panel))

        self.assertIs(router.get_panel("x"), panel)

    def test_get_panel_unknown_raises_key_error(self) -> None:
        router = PanelRouter(MagicMock())

        with self.assertRaises(KeyError):
            router.get_panel("nope")

    def test_initial_active_key_is_none(self) -> None:
        router = PanelRouter(MagicMock())

        self.assertIsNone(router.active_key)

    def test_show_hides_other_panels(self) -> None:
        router = PanelRouter(MagicMock())
        first = MagicMock()
        second = MagicMock()
        router.register(PanelSpec("first", lambda _host: first))
        router.register(PanelSpec("second", lambda _host: second))

        router.show("first")
        router.show("second")

        first.pack_forget.assert_called_once_with()
        second.pack.assert_called_once_with(fill="both", expand=True)


class PanelRouterEdgeCaseTests(unittest.TestCase):
    """Edge cases ported from SA PageRouter plus Engine-specific transaction cases."""

    def test_builder_called_once_and_panel_not_packed_on_register(self) -> None:
        build_calls: list[str] = []

        def builder(_host: Any) -> MagicMock:
            build_calls.append("called")
            return MagicMock()

        router = PanelRouter(MagicMock())
        router.register(PanelSpec("scene", builder))

        self.assertEqual(build_calls, ["called"])
        self.assertIsNone(router.active_key)

    def test_empty_key_raises_value_error(self) -> None:
        router = PanelRouter(MagicMock())
        with self.assertRaises(ValueError):
            router.register(PanelSpec("", lambda _host: MagicMock()))

    def test_duplicate_key_raises_value_error(self) -> None:
        router = PanelRouter(MagicMock())
        router.register(PanelSpec("scene", lambda _host: MagicMock()))
        with self.assertRaises(ValueError):
            router.register(PanelSpec("scene", lambda _host: MagicMock()))

    def test_whitespace_only_key_is_legal(self) -> None:
        """A whitespace key is unusual but not empty; keys are never silently
        stripped or rewritten, so `if not spec.key` must not reject it."""
        router = PanelRouter(MagicMock())
        panel = MagicMock()

        router.register(PanelSpec("   ", lambda _host: panel))

        self.assertEqual(router.registered_keys, ("   ",))
        self.assertIs(router.get_panel("   "), panel)

    def test_builder_failure_leaves_no_partial_registration(self) -> None:
        def failing_builder(_host: Any) -> Any:
            raise RuntimeError("build blew up")

        router = PanelRouter(MagicMock())

        with self.assertRaises(RuntimeError):
            router.register(PanelSpec("scene", failing_builder))

        self.assertEqual(router.registered_keys, ())

    def test_failed_registration_does_not_poison_later_registration_of_same_key(self) -> None:
        def failing_builder(_host: Any) -> Any:
            raise RuntimeError("build blew up")

        router = PanelRouter(MagicMock())
        with self.assertRaises(RuntimeError):
            router.register(PanelSpec("scene", failing_builder))

        panel = MagicMock()
        router.register(PanelSpec("scene", lambda _host: panel))

        self.assertIs(router.get_panel("scene"), panel)

    def test_showing_active_panel_is_a_noop(self) -> None:
        router, panels = _router("scene", "inspector")
        router.show("scene")
        first_pack_count = panels["scene"].pack.call_count
        first_forget_count = panels["inspector"].pack_forget.call_count

        returned = router.show("scene")  # must not re-pack or touch other panels

        self.assertIs(returned, panels["scene"])
        self.assertEqual(panels["scene"].pack.call_count, first_pack_count)
        self.assertEqual(panels["inspector"].pack_forget.call_count, first_forget_count)
        self.assertEqual(router.active_key, "scene")

    def test_unknown_key_raises_and_leaves_active_key_unchanged(self) -> None:
        router, _panels = _router("scene")
        router.show("scene")

        with self.assertRaises(KeyError):
            router.show("nope")

        self.assertEqual(router.active_key, "scene")

    def test_return_is_same_panel_object_across_switches(self) -> None:
        router, panels = _router("scene", "inspector")
        router.show("scene")
        router.show("inspector")

        router.show("scene")

        # Identity preserved: same retained object, not a new build.
        self.assertIs(router.get_panel("scene"), panels["scene"])

    def test_active_key_reflects_last_successful_show(self) -> None:
        router, _panels = _router("scene", "inspector")
        self.assertIsNone(router.active_key)
        router.show("scene")
        self.assertEqual(router.active_key, "scene")
        router.show("inspector")
        self.assertEqual(router.active_key, "inspector")

    def test_pack_failure_raises_and_restores_previous_panel(self) -> None:
        """If destination.pack() raises, active_key must not change and the
        previous panel must be re-shown; the original exception propagates."""
        panels: dict[str, MagicMock] = {}
        router = PanelRouter(MagicMock())

        good = MagicMock()
        panels["scene"] = good
        router.register(PanelSpec("scene", lambda _h: good))

        exploding = MagicMock()
        exploding.pack.side_effect = RuntimeError("layout error")
        panels["console"] = exploding
        router.register(PanelSpec("console", lambda _h: exploding))

        router.show("scene")

        with self.assertRaises(RuntimeError):
            router.show("console")

        self.assertEqual(router.active_key, "scene")
        # Previous panel must be re-packed after the failed switch.
        good.pack.assert_called()

    def test_pack_failure_with_no_previous_panel_leaves_active_key_none(self) -> None:
        """active_key must not advance when destination.pack() raises, whether
        or not a previous panel exists to restore."""
        failing = MagicMock()
        failing.pack.side_effect = RuntimeError("dead widget")

        router = PanelRouter(MagicMock())
        router.register(PanelSpec("broken", lambda _h: failing))

        with self.assertRaises(RuntimeError):
            router.show("broken")

        self.assertIsNone(router.active_key)

    def test_restoration_failure_does_not_mask_original_pack_failure(self) -> None:
        """When both the destination pack and the previous-panel restore
        fail, the ORIGINAL destination exception is what propagates."""
        router = PanelRouter(MagicMock())

        previous = MagicMock()
        previous.pack.side_effect = [None, RuntimeError("restore also failed")]
        router.register(PanelSpec("scene", lambda _h: previous))

        destination = MagicMock()
        destination.pack.side_effect = ValueError("destination pack failed")
        router.register(PanelSpec("console", lambda _h: destination))

        router.show("scene")

        with self.assertRaises(ValueError) as ctx:
            router.show("console")

        self.assertEqual(str(ctx.exception), "destination pack failed")
        self.assertEqual(router.active_key, "scene")

    def test_previous_panel_hide_failure_does_not_block_switch(self) -> None:
        """A previous panel that fails to pack_forget (e.g. it was externally
        destroyed) must not prevent switching to a healthy destination."""
        router = PanelRouter(MagicMock())

        dead_previous = MagicMock()
        dead_previous.pack_forget.side_effect = RuntimeError("widget destroyed")
        router.register(PanelSpec("dead", lambda _h: dead_previous))

        fresh = MagicMock()
        router.register(PanelSpec("fresh", lambda _h: fresh))

        router.show("dead")
        result = router.show("fresh")

        self.assertIs(result, fresh)
        self.assertEqual(router.active_key, "fresh")
        fresh.pack.assert_called_once_with(fill="both", expand=True)

    def test_alternating_switches_preserve_identity_and_never_rebuild(self) -> None:
        build_calls: dict[str, int] = {"a": 0, "b": 0}

        def build(name: str) -> Callable[[Any], MagicMock]:
            def builder(_host: Any) -> MagicMock:
                build_calls[name] += 1
                return MagicMock()

            return builder

        router = PanelRouter(MagicMock())
        router.register(PanelSpec("a", build("a")))
        router.register(PanelSpec("b", build("b")))
        panel_a = router.get_panel("a")
        panel_b = router.get_panel("b")

        for key in ("a", "b", "a", "b", "a"):
            router.show(key)

        self.assertEqual(build_calls, {"a": 1, "b": 1})
        self.assertIs(router.get_panel("a"), panel_a)
        self.assertIs(router.get_panel("b"), panel_b)

    def test_showing_active_panel_never_triggers_loader(self) -> None:
        """Navigation is visibility-only: show() on the active panel must not
        run any registered loader (loaders are only ever driven by refresh())."""
        coordinator = MagicMock()
        router = PanelRouter(MagicMock(), coordinator=coordinator)
        router.register(PanelSpec("data", lambda _h: MagicMock()))
        router.register_loader("data", lambda: "fresh", lambda _result: None)

        router.show("data")
        coordinator.run.assert_not_called()
        router.show("data")  # active-panel no-op

        coordinator.run.assert_not_called()


class PanelRouterLoaderTests(unittest.TestCase):
    def _router(self, coordinator: Any) -> tuple[PanelRouter, MagicMock]:
        router = PanelRouter(MagicMock(), coordinator=coordinator)
        panel = MagicMock()
        router.register(PanelSpec("data", lambda _host: panel))
        return router, panel

    def test_register_loader_rejects_unknown_panel(self) -> None:
        router = PanelRouter(MagicMock(), coordinator=MagicMock())
        with self.assertRaises(KeyError):
            router.register_loader("nope", lambda: None, lambda _result: None)

    def test_register_loader_replacement_for_same_key_is_supported(self) -> None:
        """Re-registering a loader for the same key replaces it (last write
        wins); no duplicate-loader rejection is needed for this router."""
        runner = DeferredRunner()
        coordinator = AppCoordinator(runner=runner, deliver=lambda callback: callback())
        router, _panel = self._router(coordinator)
        first_calls: list[str] = []
        second_calls: list[str] = []
        router.register_loader("data", lambda: "first", first_calls.append)

        router.register_loader("data", lambda: "second", second_calls.append)
        router.refresh("data")
        runner.run_next()

        self.assertEqual(first_calls, [])
        self.assertEqual(second_calls, ["second"])

    def test_refresh_without_loader_or_coordinator_is_a_noop(self) -> None:
        router = PanelRouter(MagicMock())
        router.register(PanelSpec("data", lambda _host: MagicMock()))
        self.assertIsNone(router.refresh("data"))

    def test_refresh_without_loader_but_with_coordinator_is_a_noop(self) -> None:
        router, _panel = self._router(MagicMock())
        self.assertIsNone(router.refresh("data"))

    def test_refresh_with_loader_but_no_coordinator_is_a_noop(self) -> None:
        router = PanelRouter(MagicMock())
        router.register(PanelSpec("data", lambda _host: MagicMock()))
        router.register_loader("data", lambda: "fresh", lambda _result: None)

        self.assertIsNone(router.refresh("data"))

    def test_refresh_shows_cached_result_instantly_then_reloads(self) -> None:
        runner = DeferredRunner()
        observer = ObservabilityWatcher()
        coordinator = AppCoordinator(
            runner=runner, deliver=lambda callback: callback(), observer=observer
        )
        coordinator.store("panel:data", "cached")
        router, _panel = self._router(coordinator)
        received: list[str] = []
        router.register_loader("data", lambda: "fresh", received.append)

        router.refresh("data")

        self.assertEqual(received, ["cached"])
        self.assertTrue(coordinator.in_flight("panel:data"))
        runner.run_next()
        self.assertEqual(received, ["cached", "fresh"])
        self.assertEqual(coordinator.last_result("panel:data"), "fresh")
        # Deliberate Engine adaptation: the coordinator operation key is
        # namespaced "panel:<key>" (not the bare key) because AppCoordinator
        # is shared app-wide, so an unprefixed panel key risks colliding
        # with an unrelated coordinator key elsewhere in the app.
        self.assertEqual(observer.event_count("app:panel:data", "cache_hit"), 1)

    def test_refresh_coalesces_repeated_triggers(self) -> None:
        runner = DeferredRunner()
        coordinator = AppCoordinator(runner=runner, deliver=lambda callback: callback())
        router, _panel = self._router(coordinator)
        received: list[str] = []
        router.register_loader("data", lambda: "fresh", received.append)

        first = router.refresh("data")
        second = router.refresh("data")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(runner.pending, 1)
        runner.run_next()
        runner.run_next()
        self.assertEqual(received, ["fresh", "fresh"])

    def test_loader_delegates_cache_policy_to_coordinator(self) -> None:
        coordinator = MagicMock()
        coordinator.run.return_value = 1
        router, _panel = self._router(coordinator)
        router.register_loader("data", lambda: "fresh", lambda _result: None)

        router.refresh("data")

        coordinator.last_result.assert_not_called()
        self.assertIs(
            coordinator.run.call_args.kwargs["cache_policy"],
            CachePolicy.STALE_WHILE_REFRESH,
        )
        self.assertEqual(coordinator.run.call_args.args[0], "panel:data")

    def test_refresh_on_hidden_panel_is_allowed(self) -> None:
        """Visibility and data freshness are independent: refreshing a panel
        that is not currently shown must still run its loader."""
        runner = DeferredRunner()
        coordinator = AppCoordinator(runner=runner, deliver=lambda callback: callback())
        router = PanelRouter(MagicMock(), coordinator=coordinator)
        router.register(PanelSpec("a", lambda _h: MagicMock()))
        router.register(PanelSpec("data", lambda _h: MagicMock()))
        router.show("a")  # "data" is registered but never shown
        received: list[str] = []
        router.register_loader("data", lambda: "fresh", received.append)

        generation = router.refresh("data")
        runner.run_next()

        self.assertIsNotNone(generation)
        self.assertEqual(received, ["fresh"])
        self.assertFalse(router.is_mapped("data"))

    def test_refresh_propagates_coordinator_shutdown_error(self) -> None:
        """The router adds no second exception system: a shut-down
        coordinator's RuntimeError must propagate through refresh()."""
        coordinator = AppCoordinator(runner=DeferredRunner())
        coordinator.shutdown()
        router, _panel = self._router(coordinator)
        router.register_loader("data", lambda: "fresh", lambda _result: None)

        with self.assertRaises(RuntimeError):
            router.refresh("data")


class PanelRouterIsMappedTests(unittest.TestCase):
    def test_is_mapped_reflects_active_panel(self) -> None:
        router, _panels = _router("a", "b")
        self.assertFalse(router.is_mapped("a"))
        router.show("a")
        self.assertTrue(router.is_mapped("a"))
        self.assertFalse(router.is_mapped("b"))

    def test_is_mapped_unknown_key_is_false(self) -> None:
        router, _panels = _router("a")
        self.assertFalse(router.is_mapped("nope"))


if __name__ == "__main__":
    unittest.main()
