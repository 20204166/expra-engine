"""A small, bounded arithmetic expression evaluator for engine input."""

from __future__ import annotations

import ast
import math
import operator
import sys
from collections.abc import Callable
from typing import Final

__all__ = ("ExpressionError", "evaluate")

_MAX_SOURCE_LENGTH: Final = 256
_MAX_NODES: Final = 64
_MAX_DEPTH: Final = 16
_MAX_LITERAL_DIGITS: Final = 64
_MAX_POWER_EXPONENT: Final = 1024
_MAX_ABS_RESULT: Final = sys.float_info.max
_BINARY_OPERATORS: dict[type[ast.operator], Callable[[int | float, int | float], int | float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[int | float], int | float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ExpressionError(ValueError):
    """Raised when input is not within the numeric expression contract."""


def evaluate(source: str) -> int | float:
    """Evaluate bounded arithmetic without executing source code."""
    if not isinstance(source, str) or not source.strip():
        raise ExpressionError("expression must be non-empty text")
    if len(source) > _MAX_SOURCE_LENGTH:
        raise ExpressionError("expression is too large")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, TypeError) as error:
        raise ExpressionError("malformed expression") from error

    nodes = tuple(ast.walk(tree))
    if len(nodes) > _MAX_NODES:
        raise ExpressionError("expression has too many nodes")
    try:
        value = _evaluate_node(tree.body, depth=0)
    except (ArithmeticError, OverflowError, ValueError) as error:
        if isinstance(error, ExpressionError):
            raise
        raise ExpressionError("expression could not be evaluated") from error
    if not math.isfinite(value):
        raise ExpressionError("result must be finite")
    return value


def _evaluate_node(node: ast.AST, *, depth: int) -> int | float:
    if depth > _MAX_DEPTH:
        raise ExpressionError("expression is too deeply nested")
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ExpressionError("only numeric constants are allowed")
        if len(str(node.value).replace(".", "").replace("-", "")) > _MAX_LITERAL_DIGITS:
            raise ExpressionError("numeric literal is too large")
        if not math.isfinite(node.value):
            raise ExpressionError("numeric constants must be finite")
        return node.value
    if isinstance(node, ast.UnaryOp):
        unary_operation = _UNARY_OPERATORS.get(type(node.op))
        if unary_operation is None:
            raise ExpressionError("unary operator is not allowed")
        return _finite_result(unary_operation(_evaluate_node(node.operand, depth=depth + 1)))
    if isinstance(node, ast.BinOp):
        binary_operation = _BINARY_OPERATORS.get(type(node.op))
        if binary_operation is None:
            raise ExpressionError("binary operator is not allowed")
        left = _evaluate_node(node.left, depth=depth + 1)
        right = _evaluate_node(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Pow):
            _check_power_bounds(left, right)
        return _finite_result(binary_operation(left, right))
    raise ExpressionError("only numeric arithmetic is allowed")


def _finite_result(value: int | float) -> int | float:
    if isinstance(value, bool):
        raise ExpressionError("result must be finite")
    if isinstance(value, int):
        if abs(value) > _MAX_ABS_RESULT:
            raise ExpressionError("result is too large")
    elif not math.isfinite(value):
        raise ExpressionError("result must be finite")
    return value


def _check_power_bounds(base: int | float, exponent: int | float) -> None:
    if abs(exponent) > _MAX_POWER_EXPONENT:
        raise ExpressionError("exponent is too large")
    if base == 0 or base in (1, -1) or exponent <= 0:
        return
    if math.log(abs(float(base))) * float(exponent) > math.log(_MAX_ABS_RESULT):
        raise ExpressionError("result is too large")
