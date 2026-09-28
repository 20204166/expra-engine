"""Tests for the renderer-neutral design vocabulary."""

from __future__ import annotations

import re
import unittest

from expra_engine.design.tokens import (
    CONTROL_METRICS,
    PANEL_HIERARCHY,
    RESPONSIVE_RULES,
    SEMANTIC_COLORS,
    SPACING_SCALE,
    STATE_STYLES,
    TYPOGRAPHY_SCALE,
)

_HEX6_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Keys that styles.py references directly at module-import time.  A missing key
# would raise KeyError on editor startup, so they form a hard contract.
_STYLES_COLOR_KEYS: frozenset[str] = frozenset(
    {
        "ink_muted",
        "ink_subtle",
        "accent",
        "accent_active",
        "line",
        "success",
        "warning",
        "danger",
        "disabled",
        "base",
        "surface",
        "panel",
        "elevated",
        "viewport",
        "ink",
        "selection",
    }
)
_STYLES_SPACING_KEYS: frozenset[str] = frozenset({"xs", "sm", "md", "lg"})

# The renderer-neutral weight vocabulary.  Adapters may translate to backend
# equivalents ("regular" → "normal" for Tk, 400 for CSS, etc.).
_KNOWN_WEIGHTS: frozenset[str] = frozenset({"regular", "bold", "italic", "bold italic"})


class DesignTokenTests(unittest.TestCase):
    def test_editor_font_adapter_uses_renderer_neutral_typography_tokens(self) -> None:
        import expra_engine.ui.styles as styles

        original_body = styles.TYPOGRAPHY_SCALE["body"]
        original_title = styles.TYPOGRAPHY_SCALE["title"]
        styles.TYPOGRAPHY_SCALE["body"] = {"size": 17, "weight": "regular"}
        styles.TYPOGRAPHY_SCALE["title"] = {"size": 18, "weight": "bold italic"}
        try:
            body_font = styles._font_from_token("body")
            title_font = styles._font_from_token("title")
        finally:
            styles.TYPOGRAPHY_SCALE["body"] = original_body
            styles.TYPOGRAPHY_SCALE["title"] = original_title

        self.assertEqual(body_font, ("Helvetica", 17))
        self.assertEqual(title_font, ("Helvetica", 18, "bold", "italic"))
        self.assertEqual(styles._font_from_token("title"), ("Helvetica", 18, "bold"))
        self.assertEqual(styles._font_from_token("mono", family="Courier"), ("Courier", 10))

    def test_default_accent_adapter_reads_semantic_color_tokens(self) -> None:
        import expra_engine.ui.styles as styles

        original_accent = styles.SEMANTIC_COLORS["accent"]
        original_active = styles.SEMANTIC_COLORS["accent_active"]
        styles.SEMANTIC_COLORS["accent"] = "#123456"
        styles.SEMANTIC_COLORS["accent_active"] = "#654321"
        try:
            colors = styles._default_cyan_theme()
        finally:
            styles.SEMANTIC_COLORS["accent"] = original_accent
            styles.SEMANTIC_COLORS["accent_active"] = original_active

        self.assertEqual(colors["accent"], "#123456")
        self.assertEqual(colors["accent_active"], "#654321")

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


class TestSemanticColors(unittest.TestCase):
    """Every SEMANTIC_COLORS value must be a valid #RRGGBB hex literal.

    Tk silently ignores or mis-renders shortened (#RGB), CSS-style (rgb(…)),
    or platform-specific color names on non-native backends.
    """

    def test_all_values_are_six_digit_hex(self) -> None:
        for name, value in SEMANTIC_COLORS.items():
            with self.subTest(name=name):
                self.assertRegex(
                    value,
                    _HEX6_RE,
                    f"SEMANTIC_COLORS[{name!r}] = {value!r} is not a #RRGGBB literal",
                )

    def test_styles_module_dependency_keys_are_present(self) -> None:
        """Keys that styles.py reads at module-import time must always exist."""
        for key in sorted(_STYLES_COLOR_KEYS):
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    SEMANTIC_COLORS,
                    f"SEMANTIC_COLORS is missing {key!r}, which styles.py requires",
                )

    def test_no_empty_color_names(self) -> None:
        for name in SEMANTIC_COLORS:
            with self.subTest(name=name):
                self.assertTrue(name.strip(), "SEMANTIC_COLORS contains an empty or blank key")


class TestSpacingScale(unittest.TestCase):
    """SPACING_SCALE values must be positive integers."""

    def test_required_keys_are_present(self) -> None:
        for key in sorted(_STYLES_SPACING_KEYS):
            with self.subTest(key=key):
                self.assertIn(key, SPACING_SCALE, f"SPACING_SCALE is missing {key!r}")

    def test_all_values_are_positive_integers(self) -> None:
        for name, value in SPACING_SCALE.items():
            with self.subTest(name=name):
                self.assertIsInstance(
                    value, int, f"SPACING_SCALE[{name!r}] = {value!r} is not an int"
                )
                # bool is a subclass of int; reject it because True == 1 is confusing
                self.assertNotIsInstance(value, bool, f"SPACING_SCALE[{name!r}] must not be a bool")
                self.assertGreater(value, 0, f"SPACING_SCALE[{name!r}] = {value!r} must be > 0")

    def test_scale_is_monotonically_ordered(self) -> None:
        """Smaller named sizes should be numerically smaller than larger ones."""
        ordered_keys = [k for k in ("xs", "sm", "md", "lg", "xl") if k in SPACING_SCALE]
        values = [SPACING_SCALE[k] for k in ordered_keys]
        for i in range(len(values) - 1):
            self.assertLess(
                values[i],
                values[i + 1],
                f"SPACING_SCALE[{ordered_keys[i]!r}] = {values[i]} must be < "
                f"SPACING_SCALE[{ordered_keys[i + 1]!r}] = {values[i + 1]}",
            )


class TestTypographyScale(unittest.TestCase):
    """Every TYPOGRAPHY_SCALE entry must have the required structure."""

    def test_every_entry_has_size_and_weight_keys(self) -> None:
        for name, entry in TYPOGRAPHY_SCALE.items():
            with self.subTest(name=name):
                self.assertIn("size", entry, f"TYPOGRAPHY_SCALE[{name!r}] is missing 'size'")
                self.assertIn("weight", entry, f"TYPOGRAPHY_SCALE[{name!r}] is missing 'weight'")

    def test_size_is_a_positive_integer(self) -> None:
        for name, entry in TYPOGRAPHY_SCALE.items():
            with self.subTest(name=name):
                size = entry["size"]
                self.assertIsInstance(
                    size, int, f"TYPOGRAPHY_SCALE[{name!r}]['size'] = {size!r} is not an int"
                )
                assert isinstance(size, int)  # narrows type for pyright
                self.assertNotIsInstance(size, bool)
                self.assertGreater(
                    size, 0, f"TYPOGRAPHY_SCALE[{name!r}]['size'] = {size!r} must be > 0"
                )

    def test_weight_is_from_known_vocabulary(self) -> None:
        """Renderer adapters translate the weight string; only known values are safe."""
        for name, entry in TYPOGRAPHY_SCALE.items():
            with self.subTest(name=name):
                weight = entry["weight"]
                self.assertIsInstance(
                    weight,
                    str,
                    f"TYPOGRAPHY_SCALE[{name!r}]['weight'] = {weight!r} is not a string",
                )
                self.assertIn(
                    weight,
                    _KNOWN_WEIGHTS,
                    f"TYPOGRAPHY_SCALE[{name!r}]['weight'] = {weight!r} is not in "
                    f"the known weight vocabulary {sorted(_KNOWN_WEIGHTS)}",
                )

    def test_no_extra_unknown_keys_in_entries(self) -> None:
        """Unknown extra keys would silently be ignored by adapters — catch drift early."""
        allowed = frozenset({"size", "weight"})
        for name, entry in TYPOGRAPHY_SCALE.items():
            with self.subTest(name=name):
                extra = set(entry) - allowed
                self.assertFalse(
                    extra,
                    f"TYPOGRAPHY_SCALE[{name!r}] has unexpected keys: {sorted(extra)}",
                )


class TestControlMetrics(unittest.TestCase):
    """CONTROL_METRICS values must be non-negative integers."""

    def test_all_values_are_non_negative_integers(self) -> None:
        for name, value in CONTROL_METRICS.items():
            with self.subTest(name=name):
                self.assertIsInstance(
                    value, int, f"CONTROL_METRICS[{name!r}] = {value!r} is not an int"
                )
                self.assertNotIsInstance(value, bool)
                self.assertGreaterEqual(
                    value, 0, f"CONTROL_METRICS[{name!r}] = {value!r} must be >= 0"
                )


class TestPanelHierarchy(unittest.TestCase):
    """PANEL_HIERARCHY must express a complete zero-based rank ordering.

    Adapters that use these values as array indices or z-order comparisons depend
    on: no duplicate ranks; ranks form the contiguous set {0, 1, …, n-1}.
    A gap or duplicate silently breaks layering without a runtime error.
    """

    def test_no_duplicate_ranks(self) -> None:
        values = list(PANEL_HIERARCHY.values())
        self.assertEqual(
            len(values),
            len(set(values)),
            f"PANEL_HIERARCHY contains duplicate rank values: {values}",
        )

    def test_ranks_form_contiguous_zero_based_range(self) -> None:
        values = sorted(PANEL_HIERARCHY.values())
        expected = list(range(len(values)))
        self.assertEqual(
            values,
            expected,
            f"PANEL_HIERARCHY ranks {values} are not a contiguous range {expected}",
        )

    def test_all_values_are_non_negative_integers(self) -> None:
        for name, value in PANEL_HIERARCHY.items():
            with self.subTest(name=name):
                self.assertIsInstance(value, int)
                self.assertNotIsInstance(value, bool)
                self.assertGreaterEqual(value, 0)


class TestStateStyles(unittest.TestCase):
    """STATE_STYLES modifier tuples must contain only non-empty, non-duplicate strings."""

    def test_all_modifier_strings_are_non_empty(self) -> None:
        for state, modifiers in STATE_STYLES.items():
            for i, modifier in enumerate(modifiers):
                with self.subTest(state=state, index=i):
                    self.assertIsInstance(modifier, str)
                    self.assertTrue(
                        modifier.strip(),
                        f"STATE_STYLES[{state!r}][{i}] is empty or blank",
                    )

    def test_no_duplicate_modifiers_within_a_state(self) -> None:
        for state, modifiers in STATE_STYLES.items():
            with self.subTest(state=state):
                self.assertEqual(
                    len(modifiers),
                    len(set(modifiers)),
                    f"STATE_STYLES[{state!r}] has duplicate modifiers: {modifiers}",
                )

    def test_default_state_has_no_modifiers(self) -> None:
        self.assertIn("default", STATE_STYLES)
        self.assertEqual(
            STATE_STYLES["default"],
            (),
            "the 'default' state must carry no modifiers",
        )


class TestResponsiveRules(unittest.TestCase):
    """RESPONSIVE_RULES values must be positive integers."""

    def test_all_values_are_positive_integers(self) -> None:
        for name, value in RESPONSIVE_RULES.items():
            with self.subTest(name=name):
                self.assertIsInstance(value, int)
                self.assertNotIsInstance(value, bool)
                self.assertGreater(value, 0, f"RESPONSIVE_RULES[{name!r}] = {value!r} must be > 0")


if __name__ == "__main__":
    unittest.main()
