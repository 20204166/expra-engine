from __future__ import annotations

import unittest

from expra_engine.runtime.sequence import Func, Sequence, Wait


class SequenceTests(unittest.TestCase):
    def test_func_calls_with_arguments(self) -> None:
        values: list[str] = []
        Func(values.append, ("hello",))()
        self.assertEqual(values, ["hello"])

    def test_negative_wait_raises(self) -> None:
        with self.assertRaises(ValueError):
            Wait(-1.0)

    def test_functions_execute_in_order(self) -> None:
        values: list[int] = []
        sequence = Sequence(
            Func(values.append, (1,)),
            Func(values.append, (2,)),
            Func(values.append, (3,)),
        )
        sequence.update(0.0)
        self.assertEqual(values, [1, 2, 3])
        self.assertTrue(sequence.finished)

    def test_wait_delays_next_function_and_carries_remainder(self) -> None:
        values: list[str] = []
        sequence = Sequence(Func(values.append, ("a",)), Wait(1.0), Func(values.append, ("b",)))
        sequence.update(0.0)
        sequence.update(0.5)
        self.assertEqual(values, ["a"])
        sequence.update(0.75)
        self.assertEqual(values, ["a", "b"])

    def test_loop_restarts_and_empty_sequence_finishes(self) -> None:
        counter = [0]
        sequence = Sequence(Func(counter.__setitem__, (0, 1)), loop=True)
        sequence.update(0.0)
        sequence.update(0.0)
        self.assertEqual(counter[0], 1)
        self.assertFalse(sequence.finished)
        empty = Sequence()
        empty.update(0.0)
        self.assertTrue(empty.finished)

    def test_finished_update_is_noop_and_reset_restarts(self) -> None:
        values: list[int] = []
        sequence = Sequence(Func(values.append, (1,)))
        sequence.update(0.0)
        sequence.update(0.0)
        self.assertEqual(values, [1])
        sequence.reset()
        sequence.update(0.0)
        self.assertEqual(values, [1, 1])

    def test_empty_looping_sequence_finishes(self) -> None:
        sequence = Sequence(loop=True)
        sequence.update(0.0)
        self.assertTrue(sequence.finished)


if __name__ == "__main__":
    unittest.main()
