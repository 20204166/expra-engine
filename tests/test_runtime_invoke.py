from __future__ import annotations

import unittest

from expra_engine.runtime.invoke import after, every, invoke
from expra_engine.runtime.sequence import Sequence


class InvokeTests(unittest.TestCase):
    def test_invoke_without_delay_calls_immediately(self) -> None:
        values: list[int] = []
        result = invoke(values.append, 3)
        self.assertIsNone(result)
        self.assertEqual(values, [3])

    def test_invoke_with_delay_returns_sequence(self) -> None:
        values: list[str] = []
        sequence = invoke(values.append, "done", delay=1.0)
        self.assertIsInstance(sequence, Sequence)
        assert isinstance(sequence, Sequence)
        sequence.update(0.5)
        self.assertEqual(values, [])
        sequence.update(0.5)
        self.assertEqual(values, ["done"])

    def test_after_decorator_returns_deferred_sequence(self) -> None:
        values: list[str] = []

        @after(0.5)
        def mark() -> None:
            values.append("called")

        sequence = mark()
        self.assertIsInstance(sequence, Sequence)
        assert isinstance(sequence, Sequence)
        sequence.update(0.5)
        self.assertEqual(values, ["called"])

    def test_every_decorator_ticks_at_fixed_intervals(self) -> None:
        values: list[int] = []

        @every(0.5)
        def tick() -> None:
            values.append(1)

        repeater = tick()
        repeater.update(1.1)
        self.assertEqual(values, [1, 1])
        repeater.update(0.4)
        self.assertEqual(values, [1, 1, 1])

    def test_invalid_delays_raise(self) -> None:
        with self.assertRaises(ValueError):
            invoke(lambda: None, delay=-1.0)
        with self.assertRaises(ValueError):
            after(float("inf"))
        with self.assertRaises(ValueError):
            every(0.0)


if __name__ == "__main__":
    unittest.main()
