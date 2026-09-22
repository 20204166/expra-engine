"""Pure-logic tests for the retained editor panel router."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from expra_engine.ui.navigation import PanelRouter, PanelSpec


class PanelRouterTests(unittest.TestCase):
    def test_register_and_show(self) -> None:
        router = PanelRouter(MagicMock())
        panel = MagicMock()
        router.register(PanelSpec("scene", lambda _host: panel))

        self.assertTrue(router.show("scene"))
        self.assertEqual(router.active_key, "scene")
        panel.pack.assert_called_once_with(fill="both", expand=True)

    def test_show_unknown_returns_false(self) -> None:
        router = PanelRouter(MagicMock())

        self.assertFalse(router.show("nonexistent"))
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
    """Edge cases from SA PageRouter not covered in the basic tests."""

    def _router(self, *keys: str) -> "tuple[Any, dict[str, MagicMock]]":
        panels: dict[str, MagicMock] = {}

        def build(key: str) -> "Callable[[Any], MagicMock]":
            def builder(_host: Any) -> MagicMock:
                p = MagicMock()
                panels[key] = p
                return p

            return builder

        router = PanelRouter(MagicMock())
        for k in keys:
            router.register(PanelSpec(k, build(k)))
        return router, panels

    def test_builder_called_once_and_panel_not_packed_on_register(self) -> None:
        build_calls: list[str] = []

        def builder(_host: Any) -> MagicMock:
            build_calls.append("called")
            panel = MagicMock()
            return panel

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

    def test_showing_active_panel_is_a_noop(self) -> None:
        router, panels = self._router("scene", "inspector")
        router.show("scene")
        first_pack_count = panels["scene"].pack.call_count
        first_forget_count = panels["inspector"].pack_forget.call_count

        router.show("scene")  # must not re-pack or touch other panels

        self.assertEqual(panels["scene"].pack.call_count, first_pack_count)
        self.assertEqual(panels["inspector"].pack_forget.call_count, first_forget_count)
        self.assertEqual(router.active_key, "scene")

    def test_unknown_key_returns_false_leaves_active_key_unchanged(self) -> None:
        router, _ = self._router("scene")
        router.show("scene")

        result = router.show("nope")

        self.assertFalse(result)
        self.assertEqual(router.active_key, "scene")

    def test_return_is_same_panel_object_across_switches(self) -> None:
        router, panels = self._router("scene", "inspector")
        router.show("scene")
        router.show("inspector")

        router.show("scene")

        # Identity preserved: same retained object, not a new build
        self.assertIs(router.get_panel("scene"), panels["scene"])

    def test_active_key_reflects_last_successful_show(self) -> None:
        router, _ = self._router("scene", "inspector")
        self.assertIsNone(router.active_key)
        router.show("scene")
        self.assertEqual(router.active_key, "scene")
        router.show("inspector")
        self.assertEqual(router.active_key, "inspector")

    def test_pack_failure_returns_false_and_restores_previous_panel(self) -> None:
        """If destination.pack() raises, active_key must not change and the
        previous panel must be re-shown."""
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
        result = router.show("console")

        self.assertFalse(result)
        self.assertEqual(router.active_key, "scene")
        # Previous panel must be re-packed after the failed switch.
        good.pack.assert_called()

    def test_active_key_only_set_after_successful_pack(self) -> None:
        """active_key must not advance when destination.pack() raises."""
        failing = MagicMock()
        failing.pack.side_effect = RuntimeError("dead widget")

        router = PanelRouter(MagicMock())
        router.register(PanelSpec("broken", lambda _h: failing))

        result = router.show("broken")

        self.assertFalse(result)
        self.assertIsNone(router.active_key)


if __name__ == "__main__":
    unittest.main()
