"""Tests for backend-neutral UI control state."""

import unittest

from expra_engine.ui_model.controls import (
    Button,
    ButtonVisualState,
    Progress,
    ProgressSegment,
    SelectionGroup,
    Slider,
    Toggle,
)


class TestButton(unittest.TestCase):
    def test_visual_state_transitions_cover_normal_hover_pressed_disabled_and_selected(
        self,
    ) -> None:
        button = Button()
        self.assertEqual(button.visual_state, ButtonVisualState.NORMAL)
        button.update(hovered=True)
        self.assertEqual(button.visual_state, ButtonVisualState.HOVER)
        button.update(pressed=True)
        self.assertEqual(button.visual_state, ButtonVisualState.PRESSED)
        button.update(enabled=False)
        self.assertEqual(button.visual_state, ButtonVisualState.DISABLED)
        button.update(enabled=True, hovered=False, pressed=False, selected=True)
        self.assertEqual(button.visual_state, ButtonVisualState.SELECTED)

    def test_button_update_returns_explicit_change_record(self) -> None:
        change = Button().update(hovered=True)
        self.assertEqual(
            (change.old, change.new), (ButtonVisualState.NORMAL, ButtonVisualState.HOVER)
        )


class TestToggle(unittest.TestCase):
    def test_toggle_changes_value_and_returns_change(self) -> None:
        toggle = Toggle()
        change = toggle.toggle()
        self.assertTrue(toggle.value)
        self.assertEqual((change.old, change.new), (False, True))
        toggle.set_enabled(False)
        self.assertFalse(toggle.toggle().changed)
        self.assertTrue(toggle.value)


class TestSlider(unittest.TestCase):
    def test_slider_has_default_and_snaps_live_changes_to_step(self) -> None:
        slider = Slider(0.0, 10.0, default=2.0, step=0.5)
        self.assertEqual(slider.value, 2.0)
        change = slider.live_change(3.24)
        self.assertEqual((change.old, change.new), (2.0, 3.0))
        self.assertEqual(slider.value, 3.0)

    def test_slider_clamps_min_and_max_and_commit_updates_committed_value(self) -> None:
        slider = Slider(0.0, 10.0, default=2.0, step=1.0)
        slider.live_change(-2.0)
        self.assertEqual(slider.value, 0.0)
        change = slider.commit(20.0)
        self.assertEqual((change.old, change.new), (0.0, 10.0))
        self.assertEqual(slider.committed_value, 10.0)

    def test_slider_rejects_invalid_ranges_and_step(self) -> None:
        with self.assertRaises(ValueError):
            Slider(2.0, 1.0)
        with self.assertRaises(ValueError):
            Slider(0.0, 1.0, step=0.0)
        with self.assertRaises(ValueError):
            Slider(0.0, 1.0, default=2.0)


class TestSelectionGroup(unittest.TestCase):
    def test_multi_selection_respects_minimum_and_maximum(self) -> None:
        group = SelectionGroup(("a", "b", "c"), minimum=1, maximum=2, selected=("a",))
        group.select("b")
        self.assertEqual(group.selected, ("a", "b"))
        with self.assertRaises(ValueError):
            group.select("c")
        group.select("b", selected=False)
        with self.assertRaises(ValueError):
            group.select("a", selected=False)

    def test_radio_selection_replaces_previous_selection(self) -> None:
        group = SelectionGroup(("a", "b"), mode="radio", selected=("a",))
        group.select("b")
        self.assertEqual(group.selected, ("b",))

    def test_disabled_members_do_not_change_selection(self) -> None:
        group = SelectionGroup(("a", "b"), selected=("a",), disabled=("b",))
        change = group.select("b")
        self.assertFalse(change.changed)
        self.assertEqual(group.selected, ("a",))

    def test_selection_group_rejects_duplicates_and_impossible_constraints(self) -> None:
        with self.assertRaises(ValueError):
            SelectionGroup(("a", "a"))
        with self.assertRaises(ValueError):
            SelectionGroup(("a",), minimum=2)
        with self.assertRaises(ValueError):
            SelectionGroup(("a", "b"), mode="radio", maximum=2)


class TestProgress(unittest.TestCase):
    def test_progress_clamps_value_and_keeps_optional_text_and_segments(self) -> None:
        progress = Progress(
            0.0,
            100.0,
            value=120.0,
            text="Loading",
            segments=(ProgressSegment("early", 0.0, 40.0), ProgressSegment("late", 40.0, 100.0)),
        )
        self.assertEqual(progress.value, 100.0)
        self.assertEqual(progress.text, "Loading")
        self.assertEqual(progress.segments[1].label, "late")

    def test_progress_rejects_invalid_ranges_and_segments(self) -> None:
        with self.assertRaises(ValueError):
            Progress(10.0, 0.0)
        with self.assertRaises(ValueError):
            Progress(0.0, 10.0, segments=(ProgressSegment("bad", 8.0, 2.0),))


class ButtonEdgeTests(unittest.TestCase):
    """Regressions: press → pointer-leaves → release and disabled-while-pressed."""

    def test_press_leave_release_does_not_stay_pressed(self) -> None:
        btn = Button()
        btn.update(pressed=True)
        btn.update(hovered=False)  # pointer left
        btn.update(pressed=False)
        self.assertEqual(btn.visual_state, ButtonVisualState.NORMAL)

    def test_disabled_while_pressed_shows_disabled(self) -> None:
        btn = Button()
        btn.update(pressed=True)
        btn.update(enabled=False)
        self.assertEqual(btn.visual_state, ButtonVisualState.DISABLED)

    def test_disabled_hover_does_not_show_hover(self) -> None:
        btn = Button(enabled=False)
        btn.update(hovered=True)
        self.assertEqual(btn.visual_state, ButtonVisualState.DISABLED)

    def test_state_change_reports_old_and_new(self) -> None:
        btn = Button()
        change = btn.update(hovered=True)
        self.assertEqual(change.old, ButtonVisualState.NORMAL)
        self.assertEqual(change.new, ButtonVisualState.HOVER)

    def test_no_change_change_is_false(self) -> None:
        btn = Button()
        change = btn.update()
        self.assertFalse(change.changed)


class ToggleEdgeTests(unittest.TestCase):
    def test_disabled_toggle_cannot_mutate(self) -> None:
        t = Toggle(value=False, enabled=False)
        result = t.toggle()
        self.assertFalse(t.value)
        self.assertFalse(result.changed)

    def test_repeated_toggle(self) -> None:
        t = Toggle(value=False)
        values = [t.toggle().new for _ in range(4)]
        self.assertEqual(values, [True, False, True, False])

    def test_programmatic_value_change(self) -> None:
        t = Toggle(value=False)
        t.value = True
        self.assertTrue(t.value)


class SliderEdgeTests(unittest.TestCase):
    def test_min_equals_max(self) -> None:
        s = Slider(minimum=5.0, maximum=5.0)
        self.assertEqual(s.value, 5.0)

    def test_value_outside_bounds_is_clamped(self) -> None:
        s = Slider(minimum=0.0, maximum=10.0)
        s.live_change(20.0)
        self.assertEqual(s.value, 10.0)
        s.live_change(-5.0)
        self.assertEqual(s.value, 0.0)

    def test_fractional_step(self) -> None:
        s = Slider(minimum=0.0, maximum=1.0, step=0.1, default=0.0)
        s.live_change(0.26)
        # 0.26 / 0.1 = 2.6 → rounds to 3 → 0.3
        self.assertAlmostEqual(s.value, 0.3, places=5)

    def test_negative_range(self) -> None:
        s = Slider(minimum=-10.0, maximum=-1.0, default=-5.0)
        s.live_change(-3.0)
        self.assertAlmostEqual(s.value, -3.0)

    def test_commit_fires_exactly_once_separate_from_live(self) -> None:
        s = Slider(minimum=0.0, maximum=10.0, default=0.0)
        s.live_change(5.0)
        self.assertNotEqual(s.value, s.committed_value)
        s.commit(5.0)
        self.assertEqual(s.value, s.committed_value)

    def test_release_callback_separate_from_live(self) -> None:
        s = Slider(minimum=0.0, maximum=10.0, default=0.0)
        live_calls = []
        s.live_change(3.0)
        live_calls.append(s.value)
        committed = s.commit(7.0)
        self.assertEqual(committed.new, 7.0)


if __name__ == "__main__":
    unittest.main()
