"""Tests for backend-neutral, instance-scoped pointer interaction."""

import unittest

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

        self.assertEqual(kinds(tracker.release((0.0, 0.0), target="button", timestamp=1.35)), ["release", "double_click"])

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
