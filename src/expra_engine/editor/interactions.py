"""Editor-window workflows that combine UI state with reversible commands."""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.entity import Entity
from expra_engine.core.project import ProjectError
from expra_engine.core.scene.scene_instance import (
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
)
from expra_engine.editor.commands import (
    Command,
    CompositeCommand,
    CreateEntityCommand,
    CreateSceneInstanceCommand,
    DeleteEntityCommand,
    RemoveComponentCommand,
    ReparentEntityCommand,
    SetComponentPropertyCommand,
)
from expra_engine.editor.project_paths import project_relative_path
from expra_engine.runtime.visual_components import SpriteComponent


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
    """Delete the current multi-selection as one undo entry."""
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
    """Duplicate every selected entity as one undo entry."""
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
    """Reparent a group of entities, skipping individually invalid changes."""
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
        return project_relative_path(project.path, last_save).as_posix()
    except ValueError:
        return None


def drop_asset_on_viewport(window: Any, entry: Any, x_root: int, y_root: int) -> None:
    """Place supported asset kinds at the viewport release location."""
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


__all__ = [
    "apply_component_change",
    "delete_selection",
    "drop_asset_on_viewport",
    "duplicate_selection",
    "remove_component",
    "reparent_selection_to",
]
