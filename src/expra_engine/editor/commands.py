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

from expra_engine.core.component_schema import component_type_spec

__all__ = (
    "Command",
    "CommandStack",
    "DeleteEntityCommand",
    "RenameEntityCommand",
    "SetExposedValueCommand",
    "SetComponentPropertyCommand",
    "AddComponentCommand",
    "RemoveComponentCommand",
    "apply_component_change",
    "remove_component",
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


class SetExposedValueCommand(Command):
    """Set one serialized script value by stable scene/entity/component IDs."""

    def __init__(
        self, scene: Any, entity_id: str, component_index: int, field: str, value: Any
    ) -> None:
        self._scene = scene
        self._entity_id = entity_id
        self._component_index = component_index
        entity = scene.find_entity(entity_id)
        self._component_ref = (
            entity.components[component_index]
            if entity is not None and 0 <= component_index < len(entity.components)
            else None
        )
        self._field = field
        self._new = value
        self._old: Any = None
        self._captured = False

    def _component(self) -> Any | None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None:
            return None
        if self._component_ref in entity.components:
            return self._component_ref
        if self._component_index < len(entity.components):
            return entity.components[self._component_index]
        return None

    def execute(self) -> None:
        component = self._component()
        if component is None or not hasattr(component, "exposed_values"):
            return
        if not self._captured:
            self._old = component.exposed_values.get(self._field)
            self._had_old = self._field in component.exposed_values
            self._captured = True
        component.exposed_values[self._field] = self._new

    def undo(self) -> None:
        component = self._component()
        if component is None or not hasattr(component, "exposed_values"):
            return
        if not self._had_old:
            component.exposed_values.pop(self._field, None)
        else:
            component.exposed_values[self._field] = self._old

    @property
    def description(self) -> str:
        return f"Set {self._field}"


class SetComponentPropertyCommand(Command):
    """Set a registered component property, resolving the target on execution."""

    def __init__(self, scene: Any, entity_id: str, component_type: type, field: str, value: Any):
        self._scene = scene
        self._entity_id = entity_id
        self._component_type = component_type
        self._field = field
        self._new = value
        entity = scene.find_entity(entity_id)
        self._component_ref = entity.get_component(component_type) if entity else None
        self._old: Any = None
        self._captured = False

    def _component(self) -> Any | None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None or self._component_ref is None:
            return None
        return next(
            (component for component in entity.components if component is self._component_ref),
            None,
        )

    def execute(self) -> None:
        component = self._component()
        if component is None or not hasattr(component, self._field):
            return
        if not self._captured:
            self._old = getattr(component, self._field)
            self._captured = True
        setattr(component, self._field, self._new)

    def undo(self) -> None:
        component = self._component()
        if component is not None and self._captured:
            setattr(component, self._field, self._old)

    @property
    def description(self) -> str:
        return f"Set {self._field}"


class AddComponentCommand(Command):
    def __init__(self, scene: Any, entity_id: str, component_type: type, component: Any = None):
        self._scene = scene
        self._entity_id = entity_id
        self._component_type = component_type
        self._component = component or component_type()
        self._added = False

    def execute(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None or entity.get_component(self._component_type) is not None:
            return
        entity.add_component(self._component)
        self._added = True

    def undo(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is not None and self._added:
            self._added = entity.remove_component(self._component)

    @property
    def description(self) -> str:
        return f"Add {self._component_type.__name__}"


class RemoveComponentCommand(Command):
    def __init__(self, scene: Any, entity_id: str, component: Any):
        self._scene = scene
        self._entity_id = entity_id
        self._component = component
        self._index: int | None = None
        self._removed = False

    def execute(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None or not any(component is self._component for component in entity.components):
            return
        from expra_engine.core.component_schema import registered_component_specs

        if any(
            self._component.__class__ in spec.required_types
            and entity.get_component(spec.cls) is not None
            for spec in registered_component_specs()
        ):
            return
        self._index = entity._components.index(self._component)
        self._removed = entity.remove_component(self._component)

    def undo(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if (
            entity is None
            or not self._removed
            or any(component is self._component for component in entity.components)
        ):
            return
        if self._index is None or self._index >= len(entity._components):
            entity.add_component(self._component)
        else:
            entity._components.insert(self._index, self._component)

    @property
    def description(self) -> str:
        return f"Remove {type(self._component).__name__}"


def apply_component_change(window: Any, entity_id: str, component_name: str, field: str, value: Any) -> None:
    if window._engine.run_state.name != "EDIT":
        return
    scene = window._engine.edit_scene
    try:
        spec = component_type_spec(component_name)
    except KeyError:
        return
    if scene is None:
        return
    window._command_stack.push(SetComponentPropertyCommand(scene, entity_id, spec.cls, field, value))
    window._present_all()


def remove_component(window: Any, entity_id: str, component_name: str) -> None:
    if window._engine.run_state.name != "EDIT":
        return
    scene = window._engine.edit_scene
    if scene is None:
        return
    try:
        spec = component_type_spec(component_name)
    except KeyError:
        return
    entity = scene.find_entity(entity_id)
    component = entity.get_component(spec.cls) if entity else None
    if component is None:
        return
    window._command_stack.push(RemoveComponentCommand(scene, entity_id, component))
    window._present_all()
