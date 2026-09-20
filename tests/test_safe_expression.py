import ast
import unittest
from unittest.mock import Mock, patch

import expra_engine.core.safe_expression as core_safe_expression
from expra_engine.editor.safe_expression import ExpressionError, evaluate


class SafeExpressionTests(unittest.TestCase):
    def test_evaluates_finite_numeric_arithmetic(self) -> None:
        self.assertEqual(evaluate("10+5"), 15)
        self.assertEqual(evaluate("32/2"), 16)
        self.assertEqual(evaluate("-4*3"), -12)

    def test_rejects_names_calls_attributes_and_indexing(self) -> None:
        for expression in ("value", "eval('2+2')", "value.real", "[1, 2][0]"):
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                evaluate(expression)

    def test_rejects_code_like_and_non_finite_input(self) -> None:
        for expression in (
            "__import__('os')",
            "exec('x = 1')",
            "float('nan')",
            "nan",
            "inf",
            "1e100000",
        ):
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                evaluate(expression)

    def test_rejects_malformed_and_oversized_expressions(self) -> None:
        with self.assertRaises(ExpressionError):
            evaluate("10 +")
        with self.assertRaises(ExpressionError):
            evaluate("9" * 101)
        with self.assertRaises(ExpressionError):
            evaluate("1" + "+1" * 100)

    def test_rejects_unbounded_exponentiation_before_computing_it(self) -> None:
        with patch.dict(
            core_safe_expression._BINARY_OPERATORS,
            {ast.Pow: Mock(side_effect=AssertionError)},
        ), self.assertRaises(ExpressionError):
            evaluate("10**1000000")


if __name__ == "__main__":
    unittest.main()
