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
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.entity import Entity
from expra_engine.core.project import ProjectError
from expra_engine.core.scene.scene_instance import (
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
    resolve_scene_instances,
)
from expra_engine.runtime.visual_components import SpriteComponent

__all__ = (
    "AddComponentCommand",
    "Command",
    "CommandStack",
    "CompositeCommand",
    "CreateEntityCommand",
    "CreateSceneInstanceCommand",
    "DeleteEntityCommand",
    "RemoveComponentCommand",
    "RenameEntityCommand",
    "ReparentEntityCommand",
    "SetComponentPropertyCommand",
    "SetExposedValueCommand",
    "ToggleEnabledCommand",
    "TransformEntityCommand",
    "apply_component_change",
    "delete_selection",
    "drop_asset_on_viewport",
    "duplicate_selection",
    "remove_component",
    "reparent_selection_to",
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


def apply_component_change(
    window: Any, entity_id: str, component_name: str, field: str, value: Any
) -> None:
    if window._engine.run_state.name != "EDIT":
        return
    scene = window._engine.edit_scene
    try:
        spec = component_type_spec(component_name)
    except KeyError:
        return
    if scene is None:
        return
    window._command_stack.push(
        SetComponentPropertyCommand(scene, entity_id, spec.cls, field, value)
    )
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


def delete_selection(window: Any) -> None:
    """Delete every currently multi-selected entity as one undo entry.

    Single-entity delete is handled separately by the window's own
    ``_on_hierarchy_delete`` (an unwrapped ``DeleteEntityCommand``); this is
    only reached for two or more selected entities.
    """
    if window._engine.run_state.name != "EDIT" or not window._selected_ids:
        return
    scene = window._engine.edit_scene
    if scene is None:
        return
    commands: list[Command] = []
    names: list[str] = []
    for entity_id in window._selected_ids:
        entity = scene.find_entity(entity_id)
        if entity is None:
            continue
        commands.append(DeleteEntityCommand(scene, entity))
        names.append(entity.name)
    if not commands:
        return
    window._command_stack.push(CompositeCommand(commands, f"Delete {len(commands)} entities"))
    window._console.log(f"[Editor] Deleted: {', '.join(names)}")
    window._set_selection_state(())
    window._update_undo_redo_state()
    window._present_all()


def duplicate_selection(window: Any) -> None:
    """Duplicate every selected entity (recursive clone) as one undo entry."""
    if window._engine.run_state.name != "EDIT" or not window._selected_ids:
        return
    scene = window._engine.edit_scene
    if scene is None:
        return
    commands: list[Command] = []
    new_ids: list[str] = []
    for entity_id in window._selected_ids:
        clone = scene.clone_entity(entity_id, recursive=True)
        if clone is None:
            continue
        commands.append(CreateEntityCommand(scene, clone))
        new_ids.append(clone.entity_id)
    if not commands:
        return
    description = (
        commands[0].description if len(commands) == 1 else f"Duplicate {len(commands)} entities"
    )
    command = commands[0] if len(commands) == 1 else CompositeCommand(commands, description)
    window._command_stack.push(command)
    plural = "y" if len(commands) == 1 else "ies"
    window._console.log(f"[Editor] Duplicated {len(commands)} entit{plural}")
    window._update_undo_redo_state()
    window._set_selection_state(tuple(new_ids))
    window._present_all()


def reparent_selection_to(window: Any, dragged_ids: tuple[str, ...], target_id: str | None) -> None:
    """Reparent every dragged entity onto ``target_id`` as one undo step.

    Entities already at ``target_id``, or whose reparent is invalid (self-
    parent, missing target, cycle -- see ``Scene.set_entity_parent``), are
    skipped individually with a console message rather than aborting the
    whole batch.
    """
    if window._engine.run_state.name != "EDIT" or not dragged_ids:
        return
    scene = window._engine.edit_scene
    if scene is None:
        return
    commands: list[Command] = []
    for entity_id in dragged_ids:
        entity = scene.find_entity(entity_id)
        if entity is None or entity.parent_id == target_id:
            continue
        old_parent_id = entity.parent_id
        try:
            scene.set_entity_parent(entity_id, target_id)
        except ValueError as exc:
            window._console.log(f"[Editor] Reparent skipped: {exc}", level="warning")
            continue
        # Revert the trial mutation above -- CommandStack.push() below applies
        # it for real via ReparentEntityCommand.execute(), keeping "push()
        # calls execute()" the single point of truth for the final state.
        scene.set_entity_parent(entity_id, old_parent_id)
        commands.append(ReparentEntityCommand(scene, entity_id, old_parent_id, target_id))
    if not commands:
        return
    description = (
        commands[0].description if len(commands) == 1 else f"Reparent {len(commands)} entities"
    )
    command = commands[0] if len(commands) == 1 else CompositeCommand(commands, description)
    window._command_stack.push(command)
    window._update_undo_redo_state()
    plural = "y" if len(commands) == 1 else "ies"
    window._console.log(f"[Editor] Reparented {len(commands)} entit{plural}")
    window._present_all()


def _current_scene_relative_path(window: Any, project: Any) -> str | None:
    last_save = getattr(window, "_last_save_path", None)
    if last_save is None:
        return None
    try:
        return last_save.relative_to(project.path).as_posix()
    except ValueError:
        return None


def drop_asset_on_viewport(window: Any, entry: Any, x_root: int, y_root: int) -> None:
    """Handle an asset dragged from the Assets panel and released over the viewport.

    Detects a drop by comparing the release point (root/screen coordinates)
    against the viewport canvas's own screen rectangle. Tk has no native
    OS-level drag-and-drop of its own; the alternative, ``winfo_containing``,
    depends on window-manager stacking introspection that isn't reliably
    available in a headless/no-WM Tk session (as used by this test suite),
    and this editor's panels never overlap on screen anyway, so a plain rect
    check is both simpler and more portable. A release outside that rect is
    not a drop and is ignored.
    """
    if window._engine.run_state.name != "EDIT" or entry.is_folder:
        return
    scene = window._engine.edit_scene
    if scene is None:
        return
    canvas = window._viewport._canvas
    canvas_x0, canvas_y0 = canvas.winfo_rootx(), canvas.winfo_rooty()
    canvas_x1 = canvas_x0 + canvas.winfo_width()
    canvas_y1 = canvas_y0 + canvas.winfo_height()
    if not (canvas_x0 <= x_root <= canvas_x1 and canvas_y0 <= y_root <= canvas_y1):
        return
    canvas_x = x_root - canvas_x0
    canvas_y = y_root - canvas_y0
    world_x, world_y = window._viewport._camera.unproject((float(canvas_x), float(canvas_y)))

    if entry.kind == "Scene":
        _drop_scene_instance(window, scene, entry, world_x, world_y)
    elif entry.kind == "Image":
        _drop_sprite(window, scene, entry, world_x, world_y)
    else:
        window._console.log(
            f"[Editor] Cannot place asset of type {entry.kind!r} into the viewport.",
            level="warning",
        )


def _drop_sprite(window: Any, scene: Any, entry: Any, world_x: float, world_y: float) -> None:
    entity = scene.create_entity(entry.path.stem)
    entity.add_component(TransformComponent(x=world_x, y=world_y))
    entity.add_component(SpriteComponent(asset=str(entry.logical_id)))
    window._command_stack.push(CreateEntityCommand(scene, entity))
    window._update_undo_redo_state()
    window._console.log(f"[Editor] Placed sprite: {entity.name}")
    window._set_selection_state((entity.entity_id,))
    window._present_all()


def _drop_scene_instance(
    window: Any, scene: Any, entry: Any, world_x: float, world_y: float
) -> None:
    project = window._engine.project
    if project is None or entry.logical_id is None:
        return
    source_path = entry.logical_id.path
    try:
        project._validate_scene_path(source_path)
    except ProjectError:
        window._console.log(f"[Editor] Not a placeable scene: {entry.name}", level="warning")
        return
    current_path = _current_scene_relative_path(window, project)
    if current_path is not None and current_path == source_path:
        window._console.log("[Editor] Cannot instance a scene into itself.", level="warning")
        return

    entity = Entity(entry.path.stem)
    entity.add_component(TransformComponent(x=world_x, y=world_y))
    try:
        entity.add_component(SceneInstanceComponent(source_path))
    except ValueError as exc:
        window._console.log(f"[Editor] Could not create scene instance: {exc}", level="warning")
        return

    chain = frozenset({current_path}) if current_path is not None else frozenset()
    command = CreateSceneInstanceCommand(
        scene, entity, lambda path: project.load_scene(path), chain=chain
    )
    try:
        window._command_stack.push(command)
    except (SceneInstanceSourceError, SceneInstanceCycleError) as exc:
        window._console.log(f"[Editor] Could not place scene instance: {exc}", level="warning")
        return
    window._update_undo_redo_state()
    window._console.log(f"[Editor] Placed scene instance: {entity.name}")
    window._set_selection_state((entity.entity_id,))
    window._present_all()
