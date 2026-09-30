"""Editor undo/redo command model.

Commands are immutable; the stack is mutable.  Every editor action that
should be undoable is expressed as a Command subclass with ``execute`` and
``undo`` methods.

The stack discards the redo branch when a new command is pushed after an
undo, matching standard editor behavior.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene.scene_instance import (
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
    resolve_scene_instances,
)
from expra_engine.core.script_component import ScriptComponent
from expra_engine.core.world import World

__all__ = (
    "AddComponentCommand",
    "Command",
    "CommandStack",
    "CompositeCommand",
    "CreateEntityCommand",
    "CreateSceneInstanceCommand",
    "DeleteEntityCommand",
    "MakeSceneInstanceUniqueCommand",
    "RemoveComponentCommand",
    "RenameEntityCommand",
    "ReparentEntityCommand",
    "ReplaceWorldDocumentCommand",
    "SetComponentPropertyCommand",
    "SetExposedValueCommand",
    "SetInstanceOverrideCommand",
    "ToggleEnabledCommand",
    "TransformEntityCommand",
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
        self._clean_index: int | None = 0

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._history)

    @property
    def is_dirty(self) -> bool:
        """Whether the executed command cursor differs from the last saved cursor."""
        return self._clean_index is None or self._index != self._clean_index

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
        if self._clean_index is not None and self._clean_index > self._index:
            self._clean_index = None
        del self._history[self._index :]
        command.execute()
        self._history.append(command)
        self._index += 1
        # Trim oldest commands if over limit
        if len(self._history) > self._max:
            excess = len(self._history) - self._max
            del self._history[:excess]
            self._index = max(0, self._index - excess)
            if self._clean_index is not None:
                self._clean_index = (
                    self._clean_index - excess if self._clean_index >= excess else None
                )

    def mark_clean(self) -> None:
        """Record the current undo cursor as the last successfully saved state."""
        self._clean_index = self._index

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
        self._clean_index = 0

    @property
    def history(self) -> tuple[Command, ...]:
        """Return commands in execution order (oldest first)."""
        return tuple(self._history[: self._index])


class ReplaceWorldDocumentCommand(Command):
    """Replace immutable World authoring data while preserving undo ownership."""

    def __init__(
        self,
        set_world: Callable[[World], None],
        before: World,
        after: World,
        description: str,
    ) -> None:
        self._set_world = set_world
        self._before = before
        self._after = after
        self._description = description

    def execute(self) -> None:
        self._set_world(self._after)

    def undo(self) -> None:
        self._set_world(self._before)

    @property
    def description(self) -> str:
        return self._description


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


class CreateEntityCommand(Command):
    """Add a pre-built entity to a scene (reversible by removing it)."""

    def __init__(self, scene: Any, entity: Any) -> None:
        self._scene = scene
        self._entity = entity

    def execute(self) -> None:
        if self._scene.find_entity(self._entity.entity_id) is None:
            self._scene.add_entity(self._entity)

    def undo(self) -> None:
        self._scene.remove_entity(self._entity.entity_id)

    @property
    def description(self) -> str:
        return f"Create '{self._entity.name}'"


class CreateSceneInstanceCommand(Command):
    """Add a scene-instance root and materialize its resolved subtree (reversible).

    Unlike ``CreateEntityCommand``, undo removes the ENTIRE materialized
    subtree (``recursive=True``) -- a scene instance's resolved children are
    ordinary child entities that would otherwise be orphaned by a
    non-recursive removal. ``execute`` rolls the root add back out if
    resolution fails, so a failed placement never leaves stray state.
    """

    def __init__(
        self,
        scene: Any,
        entity: Any,
        resolve_source: Callable[[str], Any],
        *,
        chain: frozenset[str] = frozenset(),
    ) -> None:
        self._scene = scene
        self._entity = entity
        self._resolve_source = resolve_source
        self._chain = chain

    def execute(self) -> None:
        added_here = False
        if self._scene.find_entity(self._entity.entity_id) is None:
            self._scene.add_entity(self._entity)
            added_here = True
        try:
            resolve_scene_instances(
                self._scene, resolve_source=self._resolve_source, chain=self._chain
            )
        except (SceneInstanceSourceError, SceneInstanceCycleError):
            if added_here:
                self._scene.remove_entity(self._entity.entity_id, recursive=True)
            raise

    def undo(self) -> None:
        self._scene.remove_entity(self._entity.entity_id, recursive=True)

    @property
    def description(self) -> str:
        return f"Create Scene Instance '{self._entity.name}'"


class ToggleEnabledCommand(Command):
    """Toggle an entity's enabled flag (reversible)."""

    def __init__(self, scene: Any, entity_id: str, old: bool, new: bool) -> None:
        self._scene = scene
        self._entity_id = entity_id
        self._old = old
        self._new = new

    def execute(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is not None:
            entity.enabled = self._new

    def undo(self) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is not None:
            entity.enabled = self._old

    @property
    def description(self) -> str:
        return "Toggle Enabled"


class TransformEntityCommand(Command):
    """Set an entity's full transform (position/rotation/scale) atomically.

    ``old``/``new`` are ``(x, y, rotation, scale_x, scale_y)`` tuples --
    capturing the whole transform in one command is what makes a viewport
    drag gesture (move/rotate/scale) collapse to exactly one undo entry,
    instead of one entry per field.
    """

    _FIELDS = ("x", "y", "rotation", "scale_x", "scale_y")

    def __init__(
        self,
        scene: Any,
        entity_id: str,
        old: tuple[float, ...],
        new: tuple[float, ...],
    ) -> None:
        self._scene = scene
        self._entity_id = entity_id
        self._old = old
        self._new = new

    def _apply(self, values: tuple[float, ...]) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None:
            return
        transform = entity.get_component(TransformComponent)
        if transform is None:
            return
        for field_name, value in zip(self._FIELDS, values, strict=True):
            setattr(transform, field_name, value)

    def execute(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)

    @property
    def description(self) -> str:
        return "Transform"


class ReparentEntityCommand(Command):
    """Set an entity's parent (reversible). Idempotent: a no-op if already there."""

    def __init__(
        self,
        scene: Any,
        entity_id: str,
        old_parent_id: str | None,
        new_parent_id: str | None,
    ) -> None:
        self._scene = scene
        self._entity_id = entity_id
        self._old = old_parent_id
        self._new = new_parent_id

    def _apply(self, parent_id: str | None) -> None:
        entity = self._scene.find_entity(self._entity_id)
        if entity is None or entity.parent_id == parent_id:
            return
        self._scene.set_entity_parent(self._entity_id, parent_id)

    def execute(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)

    @property
    def description(self) -> str:
        return "Reparent"


class CompositeCommand(Command):
    """Group several commands into one undo/redo entry.

    ``execute`` runs each sub-command's ``execute`` in order; ``undo`` runs
    each sub-command's ``undo`` in reverse order. This is the general "one
    user gesture = one undo entry" primitive -- used for multi-entity
    drag/rotate/scale as well as multi-selection delete/duplicate.
    """

    def __init__(self, commands: list[Command], description: str | None = None) -> None:
        if not commands:
            raise ValueError("CompositeCommand requires at least one command")
        self._commands = list(commands)
        self._description = description

    def execute(self) -> None:
        for command in self._commands:
            command.execute()

    def undo(self) -> None:
        for command in reversed(self._commands):
            command.undo()

    @property
    def description(self) -> str:
        if self._description is not None:
            return self._description
        if len(self._commands) == 1:
            return self._commands[0].description
        return f"{len(self._commands)} changes"


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


class SetInstanceOverrideCommand(Command):
    """Write a generated descendant's exposed-value edit to its owning instance override.

    Keeps both the authored ``SceneInstanceComponent.overrides`` map and the
    current materialized clone's exposed value in sync so the edit is visible
    immediately and round-trips through save/load resolution.
    """

    def __init__(self, scene: Any, entity_id: str, field: str, value: Any) -> None:
        self._scene = scene
        self._entity_id = entity_id
        self._field = field
        self._new = value
        origin = scene.entity_origin(entity_id)
        self._root_id: str | None = origin.instance_root_id
        entity = scene.find_entity(entity_id)
        self._entity_name: str | None = entity.name if entity is not None else None
        self._captured = False
        self._old_override: Any = None
        self._had_old_override = False
        self._old_clone: Any = None
        self._had_old_clone = False

    def _root_component(self) -> SceneInstanceComponent | None:
        root = self._scene.find_entity(self._root_id) if self._root_id is not None else None
        return root.get_component(SceneInstanceComponent) if root is not None else None

    def _clone(self) -> Any | None:
        return self._scene.find_entity(self._entity_id)

    def execute(self) -> None:
        component = self._root_component()
        clone = self._clone()
        if component is None or clone is None or self._entity_name is None:
            return
        script = clone.get_component(ScriptComponent)
        if script is None:
            return
        if not self._captured:
            existing = component.overrides.get(self._entity_name, {})
            self._had_old_override = self._field in existing
            self._old_override = existing.get(self._field)
            self._had_old_clone = self._field in script.exposed_values
            self._old_clone = script.exposed_values.get(self._field)
            self._captured = True
        component.overrides.setdefault(self._entity_name, {})[self._field] = self._new
        script.exposed_values[self._field] = self._new

    def undo(self) -> None:
        component = self._root_component()
        clone = self._clone()
        if component is None or clone is None or not self._captured:
            return
        target = component.overrides.get(self._entity_name)
        if self._had_old_override:
            if target is not None:
                target[self._field] = self._old_override
        elif target is not None:
            target.pop(self._field, None)
            if not target:
                component.overrides.pop(self._entity_name, None)
        script = clone.get_component(ScriptComponent)
        if script is not None:
            if self._had_old_clone:
                script.exposed_values[self._field] = self._old_clone
            else:
                script.exposed_values.pop(self._field, None)

    @property
    def description(self) -> str:
        return f"Set instance override {self._field}"


class MakeSceneInstanceUniqueCommand(Command):
    """Detach an instance root from its source, keeping materialized children as authored.

    Execute removes the ``SceneInstanceComponent`` and clears the root's
    materialization bookkeeping, leaving the current resolved subtree as ordinary
    authored entities. Undo restores the component and re-resolves the source,
    discarding any local authored changes made after the detach.
    """

    def __init__(self, scene: Any, root_id: str, resolve_source: Callable[[str], Any]) -> None:
        self._scene = scene
        self._root_id = root_id
        self._resolve_source = resolve_source
        self._component: SceneInstanceComponent | None = None
        self._applied = False

    def execute(self) -> None:
        root = self._scene.find_entity(self._root_id)
        if root is None or self._applied:
            return
        component = root.get_component(SceneInstanceComponent)
        if component is None:
            return
        self._component = component
        root.remove_component(component)
        children = self._scene._instance_children.pop(self._root_id, ())
        for child_id in children:
            self._scene._instance_roots.pop(child_id, None)
        self._applied = True

    def undo(self) -> None:
        if not self._applied or self._component is None:
            return
        root = self._scene.find_entity(self._root_id)
        if root is None:
            return
        stale = [e for e in self._scene.walk_hierarchy(self._root_id) if e.entity_id != self._root_id]
        stale_ids = {e.entity_id for e in stale}
        self._scene._entities = [e for e in self._scene._entities if e.entity_id not in stale_ids]
        if self._scene._entity_index is not None:
            for stale_id in stale_ids:
                self._scene._entity_index.pop(stale_id, None)
        self._scene._children_index = None
        root.add_component(self._component)
        resolve_scene_instances(self._scene, resolve_source=self._resolve_source)
        self._applied = False

    @property
    def description(self) -> str:
        return "Make Scene Instance unique"


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
        if entity is None or not any(
            component is self._component for component in entity.components
        ):
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
