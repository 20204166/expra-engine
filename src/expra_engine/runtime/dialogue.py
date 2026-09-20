"""Renderer-neutral, typed dialogue graphs with explicit state transitions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from expra_engine.core.safe_expression import ExpressionError, evaluate

__all__ = (
    "BranchLimitError",
    "DialogueAction",
    "DialogueChoice",
    "DialogueCondition",
    "DialogueError",
    "DialogueGraph",
    "DialogueNode",
    "DialogueParseError",
    "DialogueSession",
    "TerminalDialogueError",
    "parse_dialogue",
)

_ACTION_RE = re.compile(r"([A-Za-z_]\w*)\s*(\+=|-=|\*=|/=|=)\s*(.+)")
_CONDITION_RE = re.compile(r"if\s+([A-Za-z_]\w*)$")


class DialogueError(ValueError):
    """Base error for invalid dialogue data or state transitions."""


class DialogueParseError(DialogueError):
    """Raised for malformed dialogue text."""


class BranchLimitError(DialogueError):
    """Raised when a dialogue node exceeds the configured branch limit."""


class TerminalDialogueError(DialogueError):
    """Raised when a transition is requested after dialogue has ended."""


@dataclass(frozen=True, slots=True)
class DialogueCondition:
    variable: str
    expected: object = True

    def matches(self, variables: Mapping[str, object]) -> bool:
        if self.variable not in variables:
            raise KeyError(self.variable)
        return variables[self.variable] == self.expected


@dataclass(frozen=True, slots=True)
class DialogueAction:
    variable: str
    operator: str
    value: int | float

    def apply(self, variables: Mapping[str, object]) -> dict[str, object]:
        if self.variable not in variables:
            raise KeyError(self.variable)
        current = variables[self.variable]
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise TypeError(f"dialogue action requires numeric variable: {self.variable}")
        result = dict(variables)
        if self.operator == "=":
            result[self.variable] = self.value
        elif self.operator == "+=":
            result[self.variable] = current + self.value
        elif self.operator == "-=":
            result[self.variable] = current - self.value
        elif self.operator == "*=":
            result[self.variable] = current * self.value
        elif self.operator == "/=":
            result[self.variable] = current / self.value
        else:
            raise DialogueError(f"unsupported action operator: {self.operator}")
        return result


@dataclass(frozen=True, slots=True)
class DialogueChoice:
    text: str
    target_id: str
    condition: DialogueCondition | None = None
    action: DialogueAction | None = None


@dataclass(frozen=True, slots=True)
class DialogueNode:
    node_id: str
    pages: tuple[str, ...]
    choices: tuple[DialogueChoice, ...]
    condition: DialogueCondition | None = None
    action: DialogueAction | None = None

    @property
    def terminal(self) -> bool:
        return not self.choices


@dataclass(frozen=True, slots=True)
class DialogueGraph:
    nodes: Mapping[str, DialogueNode]
    start_id: str

    @property
    def start(self) -> DialogueNode:
        return self.nodes[self.start_id]


class DialogueSession:
    def __init__(
        self,
        graph: DialogueGraph,
        variables: Mapping[str, object],
        *,
        max_choices: int = 32,
        max_transitions: int = 1024,
    ) -> None:
        if max_choices < 1 or max_transitions < 1:
            raise ValueError("dialogue limits must be positive")
        self.graph = graph
        self.variables = dict(variables)
        self.current_id = graph.start_id
        self.max_choices = max_choices
        self.max_transitions = max_transitions
        self._transitions = 0

    @property
    def current(self) -> DialogueNode:
        return self.graph.nodes[self.current_id]

    @property
    def finished(self) -> bool:
        return self.current.terminal

    def available_choices(self) -> tuple[DialogueChoice, ...]:
        choices = self.current.choices
        if len(choices) > self.max_choices:
            raise BranchLimitError("dialogue node has too many choices")
        return tuple(
            choice
            for choice in choices
            if choice.condition is None or choice.condition.matches(self.variables)
        )

    def choose(self, index: int) -> DialogueNode:
        if self.finished:
            raise TerminalDialogueError("dialogue is already terminal")
        if self._transitions >= self.max_transitions:
            raise BranchLimitError("dialogue transition limit exceeded")
        choices = self.available_choices()
        try:
            choice = choices[index]
        except IndexError as error:
            raise DialogueError("choice index is out of range") from error
        if choice.action is not None:
            self.variables = choice.action.apply(self.variables)
        self.current_id = choice.target_id
        self._transitions += 1
        return self.current


def parse_dialogue(source: str) -> DialogueGraph:
    if not isinstance(source, str) or not source.strip():
        raise DialogueParseError("dialogue must be non-empty text")
    records: list[tuple[int, str, bool, DialogueCondition | None, DialogueAction | None]] = []
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        if not raw_line.strip():
            continue
        if "\t" in raw_line:
            raise DialogueParseError(f"tabs are not valid indentation on line {line_number}")
        spaces = len(raw_line) - len(raw_line.lstrip(" "))
        if spaces % 4:
            raise DialogueParseError(f"indentation must use groups of four on line {line_number}")
        text, condition, action = _parse_line(raw_line.strip(), line_number)
        is_choice = text.startswith("* ")
        if is_choice:
            text = text[2:].strip()
        if not text:
            raise DialogueParseError(f"empty dialogue content on line {line_number}")
        records.append((spaces // 4, text, is_choice, condition, action))
    if not records or records[0][0] != 0:
        raise DialogueParseError("dialogue must start at indentation level zero")

    nodes: dict[str, DialogueNode] = {}
    parents: list[str] = []
    previous_level = -1
    for index, (level, text, _is_choice, condition, action) in enumerate(records):
        if level > previous_level + 1:
            raise DialogueParseError("indentation skips a dialogue level")
        if level == 0 and index and previous_level == 0:
            raise DialogueParseError("dialogue may only have one root node")
        if level <= previous_level:
            parents = parents[:level]
        parent_id = parents[level - 1] if level else None
        node_id = f"node-{index}"
        nodes[node_id] = DialogueNode(node_id, (text,), (), condition, action)
        if parent_id is not None:
            parent = nodes[parent_id]
            choice = DialogueChoice(text, node_id, condition, action)
            nodes[parent_id] = DialogueNode(
                parent.node_id, parent.pages, (*parent.choices, choice), parent.condition, parent.action
            )
        if len(parents) > level:
            parents[level] = node_id
        else:
            parents.append(node_id)
        previous_level = level
    return DialogueGraph(nodes, "node-0")


def _parse_line(text: str, line_number: int) -> tuple[str, DialogueCondition | None, DialogueAction | None]:
    condition = None
    action = None
    if text.endswith(")") and " (" in text:
        content, metadata = text.rsplit(" (", 1)
        metadata = metadata[:-1]
        text = content.strip()
        condition_match = _CONDITION_RE.fullmatch(metadata)
        if condition_match:
            condition = DialogueCondition(condition_match.group(1))
        else:
            action_match = _ACTION_RE.fullmatch(metadata)
            if action_match is None:
                raise DialogueParseError(f"invalid dialogue metadata on line {line_number}")
            try:
                value = evaluate(action_match.group(3).strip())
            except ExpressionError as error:
                raise DialogueParseError(f"invalid action value on line {line_number}") from error
            action = DialogueAction(action_match.group(1), action_match.group(2), value)
    elif "(" in text or ")" in text:
        raise DialogueParseError(f"malformed dialogue metadata on line {line_number}")
    return text, condition, action
