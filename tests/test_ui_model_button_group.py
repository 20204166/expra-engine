from __future__ import annotations

import unittest

from expra_engine.ui_model.button_group import ButtonGroupState


class ButtonGroupTests(unittest.TestCase):
    def test_first_option_is_selected_for_positive_minimum(self) -> None:
        self.assertEqual(ButtonGroupState(["A", "B", "C"]).selected, frozenset({"A"}))

    def test_max_selection_replaces_oldest_option(self) -> None:
        group = ButtonGroupState(["A", "B", "C"], max_selection=1)
        group.select("B")
        self.assertEqual(group.selected, frozenset({"B"}))

    def test_minimum_prevents_deselect(self) -> None:
        group = ButtonGroupState(["A", "B"], min_selection=1)
        group.deselect("A")
        self.assertIn("A", group.selected)

    def test_unlimited_multi_select(self) -> None:
        group = ButtonGroupState(["A", "B", "C"], min_selection=0, max_selection=0)
        group.select("A")
        group.select("B")
        self.assertEqual(group.selected, frozenset({"A", "B"}))

    def test_invalid_and_unknown_options_raise(self) -> None:
        with self.assertRaises(ValueError):
            ButtonGroupState(["A"], min_selection=2)
        group = ButtonGroupState(["A", "B"])
        with self.assertRaises(ValueError):
            group.select("Z")
        with self.assertRaises(ValueError):
            group.deselect("Z")


if __name__ == "__main__":
    unittest.main()
