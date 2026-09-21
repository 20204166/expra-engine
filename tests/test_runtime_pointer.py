"""Tests for backend-neutral, instance-scoped pointer interaction."""

import unittest
from math import inf

from expra_engine.runtime.pointer import PointerEvent, PointerTracker


def kinds(events: tuple[PointerEvent, ...]) -> list[str]:
    return [event.kind for event in events]


class TestPointerTracker(unittest.TestCase):
    def test_enter_leave_press_and_release_are_targeted(self) -> None:
        tracker = PointerTracker()

        self.assertEqual(kinds(tracker.move((1.0, 2.0), target="button", timestamp=1.0)), ["enter"])
        self.assertEqual(kinds(tracker.press(timestamp=2.0)), ["press"])
        events = tracker.move((3.0, 4.0), target=None, timestamp=3.0)
        self.assertEqual(kinds(events), ["leave", "drag_start", "drag"])
        release = tracker.release((5.0, 6.0), target=None, timestamp=4.0)
        self.assertEqual(kinds(release), ["release", "drop"])
        self.assertIsNone(tracker.captured)

    def test_capture_keeps_release_owner_when_pointer_leaves_bounds(self) -> None:
        tracker = PointerTracker()
        tracker.move((0.0, 0.0), target="source", timestamp=1.0)
        tracker.press(timestamp=2.0)

        events = tracker.release((100.0, 100.0), target="other", timestamp=3.0)

        self.assertEqual([event.target for event in events], ["source", "source"])
        self.assertEqual(kinds(events), ["release", "click"])

    def test_double_click_requires_same_target_and_within_interval(self) -> None:
        tracker = PointerTracker(double_click_interval=0.25)
        tracker.move((0.0, 0.0), target="button", timestamp=1.0)
        tracker.press(timestamp=1.1)
        tracker.release((0.0, 0.0), target="button", timestamp=1.15)
        tracker.press(timestamp=1.3)

        self.assertEqual(
            kinds(tracker.release((0.0, 0.0), target="button", timestamp=1.35)),
            ["release", "double_click"],
        )

    def test_focus_loss_clears_held_and_capture_without_synthetic_release(self) -> None:
        tracker = PointerTracker()
        tracker.move((0.0, 0.0), target="button", timestamp=1.0)
        tracker.press(timestamp=2.0)

        self.assertEqual(kinds(tracker.focus_lost(timestamp=3.0)), ["focus_lost"])
        self.assertFalse(tracker.held)
        self.assertIsNone(tracker.captured)
        self.assertEqual(tracker.move((0.0, 0.0), target="button", timestamp=4.0), ())

    def test_focus_loss_clears_pending_double_click_history(self) -> None:
        tracker = PointerTracker(double_click_interval=1.0)
        tracker.move((0.0, 0.0), target="button", timestamp=1.0)
        tracker.press(timestamp=1.1)
        tracker.release((0.0, 0.0), target="button", timestamp=1.2)
        tracker.focus_lost(timestamp=1.3)
        tracker.press(timestamp=1.4)

        events = tracker.release((0.0, 0.0), target="button", timestamp=1.5)

        self.assertEqual(kinds(events), ["release", "click"])


if __name__ == "__main__":
    unittest.main()


class PointerTrackerEdgeTests(unittest.TestCase):
    def test_non_finite_timestamps_are_rejected(self) -> None:
        tracker = PointerTracker()
        with self.assertRaises(ValueError):
            tracker.move((0.0, 0.0), target=None, timestamp=inf)

    def test_capture_survives_release_of_one_of_multiple_buttons(self) -> None:
        tracker = PointerTracker()
        tracker.move((0.0, 0.0), target="widget", timestamp=0.0)
        tracker.press(button="primary", timestamp=0.1)
        tracker.press(button="secondary", timestamp=0.2)
        events = tracker.release((1.0, 1.0), target=None, button="primary", timestamp=0.3)

        self.assertEqual(kinds(events), ["release"])
        self.assertEqual(tracker.captured, "widget")
        self.assertEqual(tracker.held, frozenset({"secondary"}))

    def test_pointer_exits_while_pressed_does_not_lose_capture(self) -> None:
        from expra_engine.runtime.pointer import PointerTracker

        t = PointerTracker()
        t.move((50.0, 50.0), target="widget", timestamp=0.0)
        t.press(timestamp=0.1)
        # Pointer leaves widget without releasing
        t.move((200.0, 200.0), target=None, timestamp=0.2)
        # Capture should still be the original widget
        self.assertEqual(t.captured, "widget")
        self.assertTrue(t.held)

    def test_drop_event_on_release_after_drag(self) -> None:
        from expra_engine.runtime.pointer import PointerTracker

        t = PointerTracker()
        t.move((0.0, 0.0), target="src", timestamp=0.0)
        t.press(timestamp=0.1)
        # Move enough to trigger drag
        t.move((50.0, 50.0), target="dst", timestamp=0.2)
        events = t.release((50.0, 50.0), target="dst", timestamp=0.3)
        kinds = [e.kind for e in events]
        self.assertIn("drop", kinds)

    def test_click_on_different_target_does_not_double_click(self) -> None:
        from expra_engine.runtime.pointer import PointerTracker

        t = PointerTracker(double_click_interval=1.0)
        t.move((0.0, 0.0), target="a", timestamp=0.0)
        t.press(timestamp=0.1)
        t.release((0.0, 0.0), target="a", timestamp=0.2)
        t.move((10.0, 0.0), target="b", timestamp=0.3)
        t.press(timestamp=0.3)
        events2 = t.release((10.0, 0.0), target="b", timestamp=0.4)
        kinds2 = [e.kind for e in events2]
        self.assertNotIn("double_click", kinds2)

    def test_focus_lost_clears_all_state(self) -> None:
        from expra_engine.runtime.pointer import PointerTracker

        t = PointerTracker()
        t.move((5.0, 5.0), target="w", timestamp=0.0)
        t.press(timestamp=0.1)
        t.focus_lost(timestamp=0.5)
        self.assertFalse(t.held)
        self.assertIsNone(t.captured)
        self.assertFalse(t.dragging)

    def test_double_click_interval_expired(self) -> None:
        from expra_engine.runtime.pointer import PointerTracker

        t = PointerTracker(double_click_interval=0.3)
        t.move((0.0, 0.0), target="btn", timestamp=0.0)
        t.press(timestamp=0.1)
        t.release((0.0, 0.0), target="btn", timestamp=0.2)
        t.press(timestamp=0.6)  # > 0.3 s later
        events = t.release((0.0, 0.0), target="btn", timestamp=0.7)
        kinds = [e.kind for e in events]
        self.assertNotIn("double_click", kinds)
        self.assertIn("click", kinds)
