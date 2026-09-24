from __future__ import annotations

import unittest

from expra_engine.ui_model.checkbox import CheckboxState


class CheckboxTests(unittest.TestCase):
    def test_default_unchecked(self) -> None:
        self.assertFalse(CheckboxState().checked)

    def test_toggle(self) -> None:
        checkbox = CheckboxState()
        checkbox.toggle()
        self.assertTrue(checkbox.checked)
        checkbox.toggle()
        self.assertFalse(checkbox.checked)

    def test_initial_checked(self) -> None:
        self.assertTrue(CheckboxState(checked=True).checked)

    def test_toggle_from_initially_checked(self) -> None:
        checkbox = CheckboxState(checked=True)
        checkbox.toggle()
        self.assertFalse(checkbox.checked)


if __name__ == "__main__":
    unittest.main()
