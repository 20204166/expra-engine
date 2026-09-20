from __future__ import annotations

import unittest

from expra_engine.runtime.animator import AnimatorStateMachine


class AnimatorTests(unittest.TestCase):
    def _make(self) -> AnimatorStateMachine:
        return AnimatorStateMachine(
            {"idle": "clip_idle", "walk": "clip_walk", "jump": "clip_jump"},
            "idle",
        )

    def test_initial_state_and_clip(self) -> None:
        animator = self._make()
        self.assertEqual(animator.current_state, "idle")
        self.assertEqual(animator.current_clip_id, "clip_idle")
        self.assertIsNone(animator.previous_state)

    def test_transition_and_previous_state(self) -> None:
        animator = self._make()
        self.assertTrue(animator.set_state("walk"))
        self.assertEqual(animator.current_clip_id, "clip_walk")
        self.assertTrue(animator.set_state("jump"))
        self.assertEqual(animator.previous_state, "walk")

    def test_same_and_unknown_states(self) -> None:
        animator = self._make()
        self.assertFalse(animator.set_state("idle"))
        with self.assertRaises(ValueError):
            animator.set_state("fly")
        with self.assertRaises(ValueError):
            AnimatorStateMachine({"idle": "clip"}, "missing")


if __name__ == "__main__":
    unittest.main()
