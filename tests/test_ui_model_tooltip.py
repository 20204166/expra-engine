from __future__ import annotations

import unittest

from expra_engine.ui_model.tooltip import TooltipState


class TooltipStateTests(unittest.TestCase):
    def test_tooltip_becomes_visible_after_delay(self) -> None:
        tooltip = TooltipState("Help", delay=0.5)
        tooltip.start()
        tooltip.update(0.49)
        self.assertFalse(tooltip.visible)
        tooltip.update(0.01)
        self.assertTrue(tooltip.visible)

    def test_empty_text_never_becomes_visible(self) -> None:
        tooltip = TooltipState("", delay=0.0)
        tooltip.start()
        tooltip.update(1.0)
        self.assertFalse(tooltip.visible)

    def test_hide_and_invalid_values(self) -> None:
        tooltip = TooltipState("Help", delay=0.0)
        tooltip.start()
        tooltip.update(0.0)
        tooltip.hide()
        self.assertFalse(tooltip.visible)
        with self.assertRaises(ValueError):
            TooltipState("Help", delay=-1.0)
        with self.assertRaises(ValueError):
            tooltip.update(-1.0)


if __name__ == "__main__":
    unittest.main()
