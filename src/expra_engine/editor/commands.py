"""Editor undo/redo command model.

Commands are immutable; the stack is mutable.  Every editor action that
should be undoable is expressed as a Command subclass with ``execute`` and
``undo`` methods.

The stack discards the redo branch when a new command is pushed after an
undo, matching standard editor behavior.
"""

from __future__ import annotations

import abc
from typing import Any

__all__ = (
    "Command",
    "CommandStack",
    "DeleteEntityCommand",
    "RenameEntityCommand",
)


class Command(abc.ABC):
    """Abstract base for all reversible editor operations."""

    @abc.abstractmethod
    def execute(self) -> None:
        """Apply this command to the editor state."""

    @abc.abstractmethod
    def undo(self) -> None:
        """Reverse this command in the editor state."""

    @property
    def description(self) -> str:
        """Human-readable description used in menus and history panels."""
        return type(self).__name__


class CommandStack:
    """A bounded undo/redo stack.

    ``max_size`` limits how many commands are retained.  When the limit is
    reached, the oldest entry is discarded.
    """

    def __init__(self, max_size: int = 200) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max = max_size
        self._history: list[Command] = []
        self._index: int = 0  # points one past the last executed command

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._history)

    @property
    def undo_description(self) -> str | None:
        if not self.can_undo:
            return None
        return self._history[self._index - 1].description

    @property
    def redo_description(self) -> str | None:
        if not self.can_redo:
            return None
        return self._history[self._index].description

    def push(self, command: Command) -> None:
        """Execute *command* and push it onto the history.

        All redo entries (commands after the current index) are discarded.
        """
        # Discard redo branch
        del self._history[self._index :]
        command.execute()
        self._history.append(command)
        self._index += 1
        # Trim oldest commands if over limit
        if len(self._history) > self._max:
            excess = len(self._history) - self._max
            del self._history[:excess]
            self._index = max(0, self._index - excess)

    def undo(self) -> Command | None:
        """Undo the most recently executed command, returning it."""
        if not self.can_undo:
            return None
        self._index -= 1
        command = self._history[self._index]
        command.undo()
        return command

    def redo(self) -> Command | None:
        """Re-execute the next undone command, returning it."""
        if not self.can_redo:
            return None
        command = self._history[self._index]
        command.execute()
        self._index += 1
        return command

    def clear(self) -> None:
        """Discard all history."""
        self._history.clear()
        self._index = 0

    @property
    def history(self) -> tuple[Command, ...]:
        """Return commands in execution order (oldest first)."""
        return tuple(self._history[: self._index])


# ---------------------------------------------------------------------------
# Built-in editor commands
# ---------------------------------------------------------------------------


class RenameEntityCommand(Command):
    """Rename a scene entity (reversible)."""

    def __init__(self, entity: Any, old_name: str, new_name: str) -> None:
        self._entity = entity
        self._old = old_name
        self._new = new_name

    def execute(self) -> None:
        self._entity.name = self._new

    def undo(self) -> None:
        self._entity.name = self._old

    @property
    def description(self) -> str:
        return f"Rename to '{self._new}'"


class DeleteEntityCommand(Command):
    """Delete a scene entity (reversible by re-adding it)."""

    def __init__(self, scene: Any, entity: Any) -> None:
        self._scene = scene
        self._entity = entity

    def execute(self) -> None:
        self._scene.remove_entity(self._entity.entity_id)

    def undo(self) -> None:
        self._scene.add_entity(self._entity)

    @property
    def description(self) -> str:
        return f"Delete '{self._entity.name}'"
