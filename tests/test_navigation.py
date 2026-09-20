"""Pure-logic tests for the retained editor panel router."""

from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
