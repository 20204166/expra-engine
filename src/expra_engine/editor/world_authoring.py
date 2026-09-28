"""World-specific document authoring commands contributed to the editor shell."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from expra_engine.core.project import ProjectError
from expra_engine.core.scene import Level
from expra_engine.core.world import (
    LevelDescriptor,
    TransitionMode,
    World,
    WorldConnection,
)
from expra_engine.editor.commands import ReplaceWorldDocumentCommand
from expra_engine.editor.interactions import drop_asset_on_viewport
from expra_engine.runtime.level_anchor import LevelAnchorComponent, LevelAnchorKind


class WorldAuthoringWorkflow:
    """Own World graph edits while delegating persistence/runtime to canonical owners."""

    def __init__(self, window: Any) -> None:
        self.window = window

    def add_level_to_world(
        self,
        relative_path: str,
        *,
        origin: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        window = self.window
        project = window._engine.project
        world = self._active_world()
        if project is None:
            raise ProjectError("Add Level requires an active Project")
        project.document_file(relative_path)
        source = project.read_document(relative_path, observer=getattr(window, "_observer", None))
        if not isinstance(source, Level):
            raise ProjectError(f"document is not a Level: {relative_path}")
        project.register_level_path(relative_path)
        stem = Path(relative_path).name.removesuffix(".level.pb")
        instance_id = stem
        suffix = 2
        existing = {item.instance_id for item in world.levels}
        while instance_id in existing:
            instance_id = f"{stem}-{suffix}"
            suffix += 1
        descriptor = LevelDescriptor(instance_id, relative_path, origin=origin)
        updated = replace(
            world,
            levels=(*world.levels, descriptor),
            initial_level_id=world.initial_level_id or instance_id,
        )
        self._commit(world, updated, f"Add Level {instance_id}")
        window._console.log(f"[World] Added Level reference: {relative_path}")
        window._present_all()

    def update_level_placement(
        self, instance_id: str, origin: tuple[float, float]
    ) -> None:
        window = self.window
        world = self._active_world()
        descriptor = next(
            (item for item in world.levels if item.instance_id == instance_id), None
        )
        if descriptor is None:
            raise ProjectError(f"World Level instance does not exist: {instance_id}")
        updated_descriptor = replace(descriptor, origin=origin)
        if updated_descriptor == descriptor:
            return
        if descriptor.bounds is not None:
            dx = updated_descriptor.origin[0] - descriptor.origin[0]
            dy = updated_descriptor.origin[1] - descriptor.origin[1]
            updated_descriptor = replace(
                updated_descriptor,
                bounds=(
                    descriptor.bounds[0] + dx,
                    descriptor.bounds[1] + dy,
                    descriptor.bounds[2],
                    descriptor.bounds[3],
                ),
            )
        updated = replace(
            world,
            levels=tuple(
                updated_descriptor if item.instance_id == instance_id else item
                for item in world.levels
            ),
        )
        self._commit(world, updated, f"Place Level {instance_id}")
        window._present_all()

    def set_initial_level(self, instance_id: str, entrance_id: str | None = None) -> None:
        window = self.window
        world = self._active_world()
        descriptor = next(
            (item for item in world.levels if item.instance_id == instance_id), None
        )
        if descriptor is None:
            raise ProjectError(f"World Level instance does not exist: {instance_id}")
        if entrance_id is None and instance_id == world.initial_level_id:
            entrance_id = world.initial_entrance_id
        if entrance_id is not None:
            project = window._engine.project
            if project is None:
                raise ProjectError("Initial entrance validation requires an active Project")
            level = project.read_document(
                descriptor.resource_path, observer=getattr(window, "_observer", None)
            )
            anchor = level.find_anchor(entrance_id) if isinstance(level, Level) else None
            if anchor is None or anchor[1].kind not in {
                LevelAnchorKind.ENTRANCE,
                LevelAnchorKind.BOTH,
            }:
                raise ProjectError(f"initial entrance is not an entrance anchor: {entrance_id}")
        updated = replace(
            world,
            initial_level_id=instance_id,
            initial_entrance_id=entrance_id,
        )
        self._commit(world, updated, f"Set Initial Level {instance_id}")
        window._present_all()

    def add_connection(
        self,
        connection: WorldConnection,
        *,
        create_reverse: bool = False,
    ) -> None:
        window = self.window
        project = window._engine.project
        world = self._active_world()
        if project is None:
            raise ProjectError("Create Connection requires an active Project")
        if not isinstance(connection, WorldConnection):
            raise TypeError("connection must be a WorldConnection")
        if connection.bidirectional:
            raise ProjectError("Create an explicit reverse connection instead of bidirectional mode")
        descriptors = {item.instance_id: item for item in world.levels}
        routes = [connection]
        if create_reverse:
            routes.append(
                replace(
                    connection,
                    connection_id=f"{connection.connection_id}:reverse",
                    source_level_id=connection.destination_level_id,
                    source_anchor_id=connection.destination_anchor_id,
                    destination_level_id=connection.source_level_id,
                    destination_anchor_id=connection.source_anchor_id,
                )
            )
        for route in routes:
            source_descriptor = descriptors.get(route.source_level_id)
            destination_descriptor = descriptors.get(route.destination_level_id)
            if source_descriptor is None or destination_descriptor is None:
                raise ProjectError(f"connection {route.connection_id!r} references a missing Level")
            source_level = project.read_document(
                source_descriptor.resource_path, observer=getattr(window, "_observer", None)
            )
            destination_level = project.read_document(
                destination_descriptor.resource_path, observer=getattr(window, "_observer", None)
            )
            if not isinstance(source_level, Level) or not isinstance(destination_level, Level):
                raise ProjectError("World connections must reference Level documents")
            source_anchor = source_level.find_anchor(route.source_anchor_id)
            destination_anchor = destination_level.find_anchor(route.destination_anchor_id)
            if source_anchor is None or destination_anchor is None:
                raise ProjectError(f"connection {route.connection_id!r} references a missing anchor")
            if source_anchor[1].kind not in {LevelAnchorKind.EXIT, LevelAnchorKind.BOTH}:
                raise ProjectError("connection source anchor must be an exit or both-way anchor")
            if destination_anchor[1].kind not in {
                LevelAnchorKind.ENTRANCE,
                LevelAnchorKind.BOTH,
            }:
                raise ProjectError("connection destination anchor must be an entrance or both-way anchor")
            if route.transition is TransitionMode.SEAMLESS:
                source_pose = source_level.world_transform(source_anchor[0].entity_id)
                destination_pose = destination_level.world_transform(destination_anchor[0].entity_id)
                source_position = tuple(
                    source_descriptor.origin[index] + source_pose.position[index]
                    for index in range(2)
                )
                destination_position = tuple(
                    destination_descriptor.origin[index] + destination_pose.position[index]
                    for index in range(2)
                )
                if math.dist(source_position, destination_position) > 0.01:
                    raise ProjectError(
                        f"seamless connection {route.connection_id!r} endpoints are not adjacent"
                    )
        updated = replace(world, connections=(*world.connections, *routes))
        self._commit(world, updated, f"Create Connection {connection.connection_id}")
        window._present_all()

    def remove_connection(self, connection_id: str) -> None:
        window = self.window
        world = self._active_world()
        if not any(item.connection_id == connection_id for item in world.connections):
            raise ProjectError(f"World connection does not exist: {connection_id}")
        updated = replace(
            world,
            connections=tuple(
                item for item in world.connections if item.connection_id != connection_id
            ),
        )
        self._commit(world, updated, f"Remove Connection {connection_id}")
        window._present_all()

    def remove_level(self, instance_id: str) -> None:
        window = self.window
        world = self._active_world()
        if not any(item.instance_id == instance_id for item in world.levels):
            raise ProjectError(f"World Level instance does not exist: {instance_id}")
        if any(
            item.source_level_id == instance_id or item.destination_level_id == instance_id
            for item in world.connections
        ):
            raise ProjectError(
                f"remove connections referencing Level {instance_id!r} before removing it"
            )
        levels = tuple(item for item in world.levels if item.instance_id != instance_id)
        initial_level_id = world.initial_level_id
        if initial_level_id == instance_id:
            initial_level_id = levels[0].instance_id if levels else None
        updated = replace(
            world,
            levels=levels,
            initial_level_id=initial_level_id,
            initial_entrance_id=world.initial_entrance_id if initial_level_id else None,
        )
        self._commit(world, updated, f"Remove Level {instance_id}")
        window._present_all()

    def _commit(self, before: World, after: World, description: str) -> None:
        self.window._command_stack.push(
            ReplaceWorldDocumentCommand(self._install, before, after, description)
        )
        self.window._update_undo_redo_state()

    def _install(self, world: World) -> None:
        window = self.window
        project = window._engine.project
        if project is None:
            raise ProjectError("World authoring requires an active Project")
        window._active_document.document = world
        window._engine.set_world(
            world,
            project=project,
            world_resource_path=_active_world_path(window, project),
        )
        workflow = getattr(window, "_project_workflow", None)
        if workflow is not None:
            window._root.title(workflow.window_title())

    def _active_world(self) -> World:
        world = getattr(getattr(self.window, "_active_document", None), "document", None)
        if not isinstance(world, World):
            raise ProjectError("World authoring requires an active World document")
        return world


def _active_world_path(window: Any, project: Any) -> str | None:
    path = getattr(window, "_last_save_path", None)
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(project.path.resolve()).as_posix()
    except ValueError:
        return None


class WorldEditorActionsMixin:
    """Tk dialogs and drop/selection handlers for World authoring in EditorWindow."""

    def _editing_world_document(self) -> bool:
        run_state = getattr(self._engine, "run_state", None)
        return getattr(run_state, "value", run_state) == "edit" and isinstance(
            self._active_document.document, World
        )

    def _apply_world_selection(self, ids: Any) -> bool:
        if not self._editing_world_document():
            return False
        document = self._active_document.document
        level_ids = {f"level:{item.instance_id}" for item in document.levels}
        connection_ids = {f"connection:{item.connection_id}" for item in document.connections}
        groups = {"world:root", "world:levels", "world:connections"}
        self._selected_ids = tuple(
            dict.fromkeys(item for item in ids if item in level_ids | connection_ids | groups)
        )
        for action in (
            "add_entity",
            "delete_entity",
            "duplicate_selection",
            "attach_script",
            "remove_script",
        ):
            self._actions.set_enabled(action, False)
        return True

    def _on_asset_drop(self, entry: Any, root_x: int, root_y: int) -> None:
        project = self._engine.project
        if (
            project is not None
            and isinstance(self._active_document.document, World)
            and entry.kind == "Level"
        ):
            try:
                relative = entry.path.resolve().relative_to(project.path.resolve()).as_posix()
                canvas = self._viewport._canvas
                canvas_x = root_x - canvas.winfo_rootx()
                canvas_y = root_y - canvas.winfo_rooty()
                if not (0 <= canvas_x <= canvas.winfo_width() and 0 <= canvas_y <= canvas.winfo_height()):
                    return
                origin = self._viewport._camera.unproject((canvas_x, canvas_y))
                self._project_workflow.add_level_to_world(relative, origin=origin)
            except (OSError, ProjectError, ValueError) as error:
                messagebox.showerror("Add Level to World", str(error), parent=self._root)
            return
        drop_asset_on_viewport(self, entry, root_x, root_y)

    def _act_add_world_level(self) -> None:
        project = self._engine.project
        if project is None or not isinstance(self._active_document.document, World):
            return
        selected = filedialog.askopenfilename(
            title="Add Level to World",
            initialdir=str(project.levels_dir),
            filetypes=[("Level documents", "*.level.pb")],
        )
        if not selected:
            return
        try:
            relative = Path(selected).resolve().relative_to(project.path.resolve()).as_posix()
            self._project_workflow.add_level_to_world(relative)
        except (OSError, ProjectError, ValueError) as error:
            messagebox.showerror("Add Level to World", str(error), parent=self._root)

    def _act_create_world_connection(self) -> None:
        project = self._engine.project
        world = self._active_document.document
        if project is None or not isinstance(world, World) or len(world.levels) < 2:
            messagebox.showwarning(
                "Create Connection",
                "Add at least two Level references before creating a connection.",
                parent=self._root,
            )
            return
        level_ids = tuple(item.instance_id for item in world.levels)
        source_level_id = simpledialog.askstring(
            "Create Connection",
            f"Source Level ID ({', '.join(level_ids)}):",
            parent=self._root,
        )
        if source_level_id not in level_ids:
            return
        source_descriptor = next(item for item in world.levels if item.instance_id == source_level_id)
        try:
            source_level = project.read_document(source_descriptor.resource_path, observer=self._observer)
        except (OSError, ProjectError, ValueError) as error:
            messagebox.showerror("Create Connection", str(error), parent=self._root)
            return
        if not isinstance(source_level, Level):
            return
        source_anchors = tuple(
            sorted(
                marker.anchor_id
                for entity in source_level.entities
                if (marker := entity.get_component(LevelAnchorComponent)) is not None
            )
        )
        source_anchor_id = simpledialog.askstring(
            "Create Connection",
            f"Source exit anchor ({', '.join(source_anchors)}):",
            parent=self._root,
        )
        destination_level_id = simpledialog.askstring(
            "Create Connection",
            f"Destination Level ID ({', '.join(level_ids)}):",
            parent=self._root,
        )
        if destination_level_id not in level_ids:
            return
        destination_descriptor = next(
            item for item in world.levels if item.instance_id == destination_level_id
        )
        try:
            destination_level = project.read_document(
                destination_descriptor.resource_path, observer=self._observer
            )
        except (OSError, ProjectError, ValueError) as error:
            messagebox.showerror("Create Connection", str(error), parent=self._root)
            return
        if not isinstance(destination_level, Level):
            return
        destination_anchors = tuple(
            sorted(
                marker.anchor_id
                for entity in destination_level.entities
                if (marker := entity.get_component(LevelAnchorComponent)) is not None
            )
        )
        destination_anchor_id = simpledialog.askstring(
            "Create Connection",
            f"Destination entrance anchor ({', '.join(destination_anchors)}):",
            parent=self._root,
        )
        if not source_anchor_id or not destination_anchor_id:
            return
        transition_name = simpledialog.askstring(
            "Create Connection",
            "Transition mode (seamless, fade, instant, loading):",
            initialvalue=TransitionMode.SEAMLESS.value,
            parent=self._root,
        )
        if not transition_name:
            return
        try:
            transition = TransitionMode(transition_name.strip().casefold())
            base_id = f"{source_level_id}.{source_anchor_id}-{destination_level_id}.{destination_anchor_id}"
            connection_ids = {item.connection_id for item in world.connections}
            connection_id = base_id
            counter = 2
            while connection_id in connection_ids:
                connection_id = f"{base_id}-{counter}"
                counter += 1
            connection = WorldConnection(
                connection_id,
                source_level_id,
                source_anchor_id,
                destination_level_id,
                destination_anchor_id,
                transition=transition,
            )
            source_marker = source_level.find_anchor(source_anchor_id)
            destination_marker = destination_level.find_anchor(destination_anchor_id)
            create_reverse = (
                source_marker is not None
                and destination_marker is not None
                and source_marker[1].kind is LevelAnchorKind.BOTH
                and destination_marker[1].kind is LevelAnchorKind.BOTH
                and messagebox.askyesno(
                    "Create Reverse Connection?",
                    "Create a separate reverse connection?",
                    parent=self._root,
                )
            )
            self._project_workflow.add_world_connection(
                connection, create_reverse=create_reverse
            )
        except (OSError, ProjectError, TypeError, ValueError) as error:
            messagebox.showerror("Create Connection", str(error), parent=self._root)

    def _open_world_level(self, instance_id: str) -> None:
        world = self._active_document.document
        if not isinstance(world, World):
            return
        descriptor = next(
            (item for item in world.levels if item.instance_id == instance_id), None
        )
        if descriptor is not None:
            self._project_workflow.open_document(descriptor.resource_path)

    def _on_world_level_placement(
        self, instance_id: str, origin: tuple[float, float]
    ) -> None:
        try:
            self._project_workflow.update_level_placement(instance_id, origin)
        except (ProjectError, TypeError, ValueError) as error:
            messagebox.showerror("World Placement", str(error), parent=self._root)

    def _on_world_set_initial_level(self, instance_id: str) -> None:
        try:
            self._project_workflow.set_initial_level(instance_id)
        except (ProjectError, TypeError, ValueError) as error:
            messagebox.showerror("Set Initial Level", str(error), parent=self._root)

    def _on_world_remove_item(self, selection: str) -> None:
        try:
            if selection.startswith("level:"):
                self._project_workflow.remove_level_from_world(selection.removeprefix("level:"))
            elif selection.startswith("connection:"):
                self._project_workflow.remove_world_connection(
                    selection.removeprefix("connection:")
                )
        except (ProjectError, TypeError, ValueError) as error:
            messagebox.showerror("Remove World Item", str(error), parent=self._root)
