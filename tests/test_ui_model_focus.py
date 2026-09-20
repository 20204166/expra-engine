"""Tests for deterministic renderer-neutral focus traversal."""

import unittest
from threading import Thread

from expra_engine.ui_model.focus import FocusEntry, FocusOrder


class TestFocusOrder(unittest.TestCase):
    def test_next_and_previous_follow_declared_order(self) -> None:
        order = FocusOrder((FocusEntry("a"), FocusEntry("b"), FocusEntry("c")))

        self.assertEqual(order.next("a"), "b")
        self.assertEqual(order.previous("c"), "b")
        self.assertEqual(order.next(), "a")
        self.assertEqual(order.previous(), "c")

    def test_disabled_and_skipped_entries_are_not_focusable(self) -> None:
        order = FocusOrder(
            (
                FocusEntry("a"),
                FocusEntry("disabled", enabled=False),
                FocusEntry("skipped", skip=True),
                FocusEntry("b"),
            )
        )

        self.assertEqual(order.next("a"), "b")
        self.assertEqual(order.previous("b"), "a")
        self.assertEqual(order.next("disabled"), "b")

    def test_wrap_policy_is_explicit_and_non_wrapping_ends_with_none(self) -> None:
        non_wrapping = FocusOrder((FocusEntry("a"), FocusEntry("b")))
        wrapping = FocusOrder((FocusEntry("a"), FocusEntry("b")), wrap=True)

        self.assertIsNone(non_wrapping.next("b"))
        self.assertIsNone(non_wrapping.previous("a"))
        self.assertEqual(wrapping.next("b"), "a")
        self.assertEqual(wrapping.previous("a"), "b")

    def test_wrapping_order_with_no_focusable_entries_returns_none(self) -> None:
        order = FocusOrder((FocusEntry("disabled", enabled=False),), wrap=True)
        result: list[str | None] = []
        worker = Thread(target=lambda: result.append(order.next("disabled")), daemon=True)

        worker.start()
        worker.join(timeout=0.1)

        self.assertFalse(worker.is_alive(), "focus traversal did not terminate")
        self.assertEqual(result, [None])


if __name__ == "__main__":
    unittest.main()
