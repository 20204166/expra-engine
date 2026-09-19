"""Tests for the renderer-neutral design vocabulary."""

import unittest

from expra_engine.design.tokens import (
    CONTROL_METRICS,
    RESPONSIVE_RULES,
    SEMANTIC_COLORS,
    SPACING_SCALE,
    STATE_STYLES,
    TYPOGRAPHY_SCALE,
)


class DesignTokenTests(unittest.TestCase):
    def test_shared_tokens_cover_runtime_ui_concepts(self) -> None:
        self.assertEqual(SPACING_SCALE["xs"], 4)
        self.assertEqual(SPACING_SCALE["xl"], 24)
        self.assertIn("accent", SEMANTIC_COLORS)
        self.assertIn("selected", STATE_STYLES)
        self.assertIn("body", TYPOGRAPHY_SCALE)
        self.assertIn("corner_radius", CONTROL_METRICS)
        self.assertIn("safe_area_gutter", RESPONSIVE_RULES)

    def test_design_package_does_not_import_editor_toolkits(self) -> None:
        import expra_engine.design.tokens as tokens

        self.assertNotIn("tkinter", tokens.__dict__)
        self.assertNotIn("ttk", tokens.__dict__)
        self.assertNotIn("ttkbootstrap", tokens.__dict__)


if __name__ == "__main__":
    unittest.main()
