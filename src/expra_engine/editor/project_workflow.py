"""Editor bridge for the headless canonical Project workflow."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Level, Scene
from expra_engine.core.scene.document_codec import canonical_pb_path
from expra_engine.core.world import World, WorldConnection
from expra_engine.editor.project_process import ProjectProcessController
from expra_engine.editor.world_authoring import WorldAuthoringWorkflow
from expra_engine.messages import project as project_messages
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_registry import ScriptRegistry


class ProjectWorkflow:
    """Keep project dialogs and switching policy outside the editor shell."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self._pending_restore: tuple[Any, Path | None] | None = None
        self._project_process_controller = ProjectProcessController(window)
        self.world_authoring = WorldAuthoringWorkflow(window)

    def new_project(self) -> None:
        window = self.window
        if not self._confirm_switch():
            return
        name = simpledialog.askstring("New Project", "Project name:", parent=window._root)
        location = filedialog.askdirectory(title="Choose project location") if name else ""
        if not name or not location:
            return
        try:
            project = Project.create(name, Path(location) / name)
            self.open_loaded(project)
        except (OSError, ProjectError) as exc:
            messagebox.showerror("New Project", str(exc), parent=window._root)

    def open_project(self) -> None:
        window = self.window
        if not self._confirm_switch():
            return
        selected = filedialog.askdirectory(title="Open Expra Project")
        if not selected:
            return
        try:
            project = Project.load(Path(selected))
            self.open_loaded(project)
        except (OSError, ProjectError) as exc:
            messagebox.showerror("Open Project", str(exc), parent=window._root)

    def open_project_manifest(self) -> None:
        window = self.window
        if not self._confirm_switch():
            return
        selected = filedialog.askopenfilename(
            title="Open Expra Project Manifest",
            filetypes=[("Expra project", "project.json"), ("JSON files", "*.json")],
        )
        if not selected:
            return
        try:
            self.open_loaded(Project.load(Path(selected)))
        except (OSError, ProjectError) as exc:
            messagebox.showerror("Open Project", str(exc), parent=window._root)

    def open_recent(self, path: str) -> None:
        if not self._confirm_switch():
            return
        try:
            self.open_loaded(Project.load(Path(path)))
        except (OSError, ProjectError) as exc:
            self.window._console.log(
                f"[Editor] Could not open recent project: {exc}", level="error"
            )

    def import_assets(self) -> None:
        window = self.window
        project = window._engine.project
        if project is None:
            return
        for filename in filedialog.askopenfilenames(title="Import Assets"):
            try:
                resource = project.import_asset(Path(filename))
            except (OSError, ProjectError) as exc:
                messagebox.showerror("Import Asset", str(exc), parent=window._root)
                continue
            window._console.log(f"[Editor] Imported asset: {resource}")
        window._assets.refresh()

    def open_asset(self, entry: Any) -> None:
        """Open a Scene, Level, or World asset through the typed Project workflow."""
        window = self.window
        project = window._engine.project
        if project is not None and entry.kind in {"Scene", "Level", "World"}:
            try:
                relative = entry.path.resolve().relative_to(project.path.resolve()).as_posix()
            except ValueError:
                window._console.log(
                    "[Assets] Document is outside the current project", level="error"
                )
                return
            self.open_document(relative)
            return
        if entry.logical_id is not None:
            window._console.log(f"[Assets] Open: {entry.logical_id}", level="info")

    def configure_input(self) -> None:
        window = self.window
        project = window._engine.project
        if project is None:
            return
        action = simpledialog.askstring("Input Settings", "Action name:", parent=window._root)
        physical = simpledialog.askstring(
            "Input Settings",
            "Physical binding (for example keyboard:left):",
            parent=window._root,
        )
        if not action or not physical:
            return
        try:
            project.set_input_binding(action, physical)
            project.save()
            device, control = physical.strip().lower().split(":", 1)
            project_engine = window._engine
            project_engine.input_map.bind(ActionId(action.strip()), PhysicalInput(device, control))
        except (OSError, ProjectError) as exc:
            messagebox.showerror("Input Settings", str(exc), parent=window._root)
            return
        window._console.log(f"[Editor] Input binding updated: {action}")

    def close_project(self) -> None:
        window = self.window
        if not self._confirm_switch():
            return
        self.stop_project()
        if window._engine.run_state.value != "edit":
            window._engine.stop()
        self._pending_restore = None
        window._engine.set_project(None)
        window._engine.set_scene(None)
        window._active_document.open(None)
        window._viewport.set_resource_service(None)
        window._editor_context = replace(window._editor_context, project=None)
        window._command_stack.clear()
        window._selected_ids = ()
        window._actions.set_enabled("close_project", False)
        window._actions.set_enabled("delete_entity", False)
        window._actions.set_enabled("duplicate_selection", False)
        window._update_project_actions()
        window._root.title("Expra Editor")
        window._present_all()

    def _confirm_switch(self) -> bool:
        """Guard project transitions when the command history has edits."""
        window = self.window
        if window._engine.project is None:
            return True
        if not window._active_document.is_dirty:
            return True
        decision = messagebox.askyesnocancel(
            "Unsaved Changes",
            "The current project has unsaved changes. Save before continuing?",
            parent=window._root,
        )
        if decision is None:
            return False
        if decision:
            window._act_save_scene_silent()
        return True

    def open_loaded(self, project: Project) -> None:
        window = self.window
        document = project.load_document(observer=window._observer)
        self.stop_project()
        runtime_preview = getattr(window, "_runtime_preview", None)
        if runtime_preview is not None:
            runtime_preview.stop()
        run_state = getattr(window._engine, "run_state", None)
        if getattr(run_state, "value", run_state) != "edit":
            window._engine.stop()
        window._engine.set_project(project)
        if isinstance(document, World):
            window._engine.set_scene(None)
            window._engine.set_world(
                document,
                project=project,
                world_resource_path=project.entrypoint,
            )
        elif isinstance(document, Scene):
            window._engine.set_scene(document)
        else:
            raise ProjectError("project entrypoint must resolve to a Scene, Level, or World")
        window._active_document.open(document, project.document_file())
        window._viewport.set_resource_service(project.resource_service(observer=window._observer))
        window._engine.set_script_registry(ScriptRegistry(project.path))
        window._editor_context = replace(window._editor_context, project=project)
        window._command_stack.clear()
        window._assets.set_root_directory(project.path)
        recent = [str(project.path), *window._preferences.recent_projects]
        window._preferences = replace(
            window._preferences,
            recent_projects=tuple(dict.fromkeys(recent))[:10],
        )
        window._selected_ids = ()
        window._last_save_path = project.document_file()
        window._root.title(self.window_title())
        window._update_project_actions()
        window._console.log(f"[Editor] Opened project: {project.name}")
        window._present_all()

    # ------------------------------------------------------------------
    # Multi-level (scene) workflow -- spec section 22
    # ------------------------------------------------------------------

    def _current_relative_path(self, project: Project) -> str | None:
        window = self.window
        if window._last_save_path is None:
            return None
        try:
            return window._last_save_path.resolve().relative_to(project.path).as_posix()
        except ValueError:
            return None

    def window_title(self) -> str:
        """Expose both the active resource path and its authored Expra semantics."""
        window = self.window
        project = window._engine.project
        if project is None:
            return "Expra Editor"
        document = window._active_document.document
        kind = document.document_kind.value.upper() if document is not None else "DOCUMENT"
        relative = self._current_relative_path(project)
        if relative is None:
            return f"{project.name} — {kind} — Expra Editor"
        suffix = " (main)" if relative == project.entrypoint else ""
        return f"{project.name} — {relative}{suffix} — {kind} — Expra Editor"

    def open_scene(self, relative_path: str | None = None) -> None:
        """Compatibility wrapper for opening a typed project document."""
        self.open_document(relative_path)

    def open_document(self, relative_path: str | None = None) -> None:
        """Open a Scene, Level, or World through the canonical Project codec."""
        window = self.window
        project = window._engine.project
        if project is None:
            return
        if relative_path is None:
            selected = filedialog.askopenfilename(
                title="Open Document",
                initialdir=str(project.path),
                filetypes=[
                    ("Scene documents", "*.scene.pb"),
                    ("Level documents", "*.level.pb"),
                    ("World documents", "*.world.pb"),
                    ("Legacy JSON", "*.json"),
                ],
            )
            if not selected:
                return
            try:
                relative_path = Path(selected).resolve().relative_to(project.path).as_posix()
            except ValueError:
                messagebox.showerror(
                    "Open Document", "Document must be inside the project.", parent=window._root
                )
                return
        if not self._confirm_switch():
            return
        try:
            document = project.load_document(relative_path, observer=window._observer)
        except ProjectError as exc:
            messagebox.showerror("Open Document", str(exc), parent=window._root)
            return
        if isinstance(document, World):
            window._engine.set_scene(None)
            window._engine.set_world(
                document,
                project=project,
                world_resource_path=relative_path,
            )
        elif isinstance(document, Scene):
            window._engine.set_scene(document)
        else:
            messagebox.showerror("Open Document", "Unsupported document kind.", parent=window._root)
            return
        document_path = project.document_file(relative_path)
        window._active_document.open(document, document_path)
        window._last_save_path = document_path
        window._selected_ids = ()
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Opened document: {relative_path}")
        window._present_all()

    def new_world(self, name: str | None = None) -> None:
        """Compatibility wrapper for the canonical typed New Document workflow."""
        self.new_document(DocumentKind.WORLD, name)

    def new_level(self, name: str | None = None) -> None:
        """Compatibility wrapper for the canonical typed New Document workflow."""
        self.new_document(DocumentKind.LEVEL, name)

    def new_document(
        self,
        kind: DocumentKind | str,
        name: str | None = None,
    ) -> None:
        """Create and open a Scene, Level, or World through one typed workflow."""
        window = self.window
        project = window._engine.project
        try:
            document_kind = (
                DocumentKind(kind.strip().casefold())
                if isinstance(kind, str)
                else DocumentKind(kind)
            )
        except (TypeError, ValueError):
            messagebox.showerror(
                "New Document", "Choose Scene, Level, or World.", parent=window._root
            )
            return
        if document_kind not in {DocumentKind.SCENE, DocumentKind.LEVEL, DocumentKind.WORLD}:
            messagebox.showerror(
                "New Document", "Choose Scene, Level, or World.", parent=window._root
            )
            return
        if project is None and document_kind is not DocumentKind.SCENE:
            messagebox.showwarning(
                "New Document",
                "Open a project before creating a Level or World.",
                parent=window._root,
            )
            return
        if not self._confirm_switch():
            return
        if name is None:
            name = simpledialog.askstring(
                "New Document", f"{document_kind.value.title()} name:", parent=window._root
            )
        if not name or not name.strip():
            return
        normalized_name = name.strip()
        if document_kind is DocumentKind.SCENE:
            document: Scene | World = Scene(normalized_name, scene_id=str(uuid.uuid4()))
            relative_path = (
                f"scenes/{canonical_pb_path(Path(normalized_name).name, DocumentKind.SCENE)}"
            )
        elif document_kind is DocumentKind.LEVEL:
            document = Level(normalized_name, scene_id=str(uuid.uuid4()))
            relative_path = (
                f"levels/{canonical_pb_path(Path(normalized_name).name, DocumentKind.LEVEL)}"
            )
        else:
            document = World(normalized_name, world_id=str(uuid.uuid4()))
            relative_path = (
                f"worlds/{canonical_pb_path(Path(normalized_name).name, DocumentKind.WORLD)}"
            )
        if project is not None:
            try:
                target = project.document_file(relative_path)
                if target.exists():
                    raise ProjectError(f"Document already exists: {relative_path}")
                project.save_document(document, relative_path)
            except (OSError, ProjectError, ValueError) as error:
                messagebox.showerror("New Document", str(error), parent=window._root)
                return
        if isinstance(document, World):
            window._engine.set_scene(None)
            window._engine.set_world(
                document,
                project=project,
                world_resource_path=relative_path,
            )
        else:
            window._engine.set_scene(document)
        document_path = project.document_file(relative_path) if project is not None else None
        window._active_document.open(document, document_path)
        window._last_save_path = document_path
        window._selected_ids = ()
        window._root.title(self.window_title())
        window._console.log(
            f"[Editor] Created {document_kind.value.title()}: "
            f"{relative_path if project is not None else normalized_name}"
        )
        window._present_all()

    def add_level_to_world(
        self,
        relative_path: str,
        *,
        origin: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Compatibility delegate to the canonical World authoring contributor."""
        self.world_authoring.add_level_to_world(relative_path, origin=origin)

    def update_level_placement(self, instance_id: str, origin: tuple[float, float]) -> None:
        self.world_authoring.update_level_placement(instance_id, origin)

    def set_initial_level(self, instance_id: str, entrance_id: str | None = None) -> None:
        self.world_authoring.set_initial_level(instance_id, entrance_id)

    def add_world_connection(
        self,
        connection: WorldConnection,
        *,
        create_reverse: bool = False,
    ) -> None:
        self.world_authoring.add_connection(connection, create_reverse=create_reverse)

    def remove_world_connection(self, connection_id: str) -> None:
        self.world_authoring.remove_connection(connection_id)

    def remove_level_from_world(self, instance_id: str) -> None:
        self.world_authoring.remove_level(instance_id)

    def save_scene_as(self) -> None:
        """Compatibility wrapper for typed active-document Save As."""
        self.save_active_document_as()

    def save_active_document_as(self) -> None:
        """Save the active typed document to a new path, then keep editing it there."""
        window = self.window
        document = window._active_document.document
        if document is None:
            messagebox.showwarning("Save As", "No document to save.", parent=window._root)
            return
        project = window._engine.project
        is_world = isinstance(document, World)
        is_level = isinstance(document, Level)
        extension = ".world.pb" if is_world else ".level.pb" if is_level else ".scene.pb"
        file_type = (
            "World documents" if is_world else "Level documents" if is_level else "Scene documents"
        )
        initial_dir = (
            (
                project.worlds_dir
                if is_world
                else project.levels_dir
                if is_level
                else project.scenes_dir
            )
            if project is not None
            else None
        )
        document_label = "World" if is_world else "Level" if is_level else "Scene"
        path = filedialog.asksaveasfilename(
            title=f"Save {document_label} As",
            defaultextension=extension,
            filetypes=[(file_type, f"*{extension}")]
            + ([] if is_world else [("Legacy JSON", "*.json")]),
            initialdir=str(initial_dir) if initial_dir is not None else None,
        )
        if not path:
            return
        target = Path(path)
        if project is None:
            if is_world:
                messagebox.showerror(
                    "Save World As",
                    "World documents must be saved inside a project.",
                    parent=window._root,
                )
                return
            try:
                target.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Save Scene As", str(exc), parent=window._root)
                return
            window._last_save_path = target
            window._active_document.mark_saved(target)
            window._console.log(f"[Editor] Scene saved as: {target}")
            return
        try:
            relative = target.resolve().relative_to(project.path.resolve()).as_posix()
            project.save_document(document, relative)
        except (OSError, ProjectError, ValueError) as exc:
            messagebox.showerror("Save Scene As", str(exc), parent=window._root)
            return
        window._last_save_path = project.document_file(relative)
        window._active_document.mark_saved(window._last_save_path)
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Scene saved as: {relative}")

    def save_scene(self) -> None:
        """Compatibility wrapper for the active typed-document Save action."""
        self.save_active_document()

    def save_active_document(self) -> None:
        window = self.window
        document = window._active_document.document
        if document is None:
            messagebox.showwarning("Save Document", "No document to save.")
            return
        project = window._engine.project
        if project is not None and window._last_save_path is not None:
            relative = window._last_save_path.resolve().relative_to(project.path)
            if relative.suffix.casefold() == ".json":
                mapping = project.migrate_to_protobuf()
                relative = Path(mapping.get(relative.as_posix(), relative.as_posix()))
                window._last_save_path = project.document_file(relative.as_posix())
                window._console.log("[Editor] Migrated legacy JSON documents to canonical PB")
            project.save_document(document, relative.as_posix())
            window._active_document.mark_saved(window._last_save_path)
            window._console.log(f"[Editor] Scene saved: {window._last_save_path}")
            return
        path = filedialog.asksaveasfilename(
            title="Save Scene",
            defaultextension=".json",
            filetypes=[("Scene files", "*.json")],
        )
        if path:
            window._last_save_path = Path(path)
            self.save_scene_silent()
            window._console.log(f"[Editor] Scene saved: {path}")

    def save_scene_silent(self) -> None:
        """Compatibility wrapper for typed-document autosave/save prompts."""
        self.save_active_document_silent()

    def save_active_document_silent(self) -> None:
        """Save to the last selected path without opening a dialog."""
        window = self.window
        document = window._active_document.document
        if window._last_save_path is None or document is None:
            return
        project = window._engine.project
        if project is None:
            if isinstance(document, World):
                raise ProjectError("World documents must be saved through their Project")
            window._last_save_path.write_text(
                json.dumps(document.to_dict(), indent=2), encoding="utf-8"
            )
            window._active_document.mark_saved(window._last_save_path)
            return
        relative = window._last_save_path.resolve().relative_to(project.path).as_posix()
        if relative.casefold().endswith(".json"):
            mapping = project.migrate_to_protobuf()
            relative = mapping.get(relative, relative)
            window._last_save_path = project.document_file(relative)
            window._console.log("[Editor] Migrated legacy JSON documents to canonical PB")
        project.save_document(document, relative)
        window._active_document.mark_saved(window._last_save_path)

    def duplicate_scene(self, name: str | None = None) -> None:
        """Compatibility wrapper for typed active-document duplication."""
        self.duplicate_document(name)

    def duplicate_document(self, name: str | None = None) -> None:
        """Duplicate the active document while preserving referenced Level paths."""
        window = self.window
        project = window._engine.project
        document = window._active_document.document
        if project is None or document is None:
            return
        if name is None:
            name = simpledialog.askstring("Duplicate Document", "New name:", parent=window._root)
        if not name:
            return
        if isinstance(document, World):
            relative = f"worlds/{canonical_pb_path(Path(name).name, DocumentKind.WORLD)}"
        elif isinstance(document, Level):
            relative = f"levels/{canonical_pb_path(Path(name).name, DocumentKind.LEVEL)}"
        else:
            relative = f"scenes/{canonical_pb_path(Path(name).name, DocumentKind.SCENE)}"
        if project.document_file(relative).exists():
            messagebox.showerror(
                "Duplicate Document", f"Document already exists: {relative}", parent=window._root
            )
            return
        data = document.to_dict()
        data["world_id" if isinstance(document, World) else "scene_id"] = str(uuid.uuid4())
        data["name"] = name
        duplicate = (
            World.from_dict(data)
            if isinstance(document, World)
            else Level.from_dict(data)
            if isinstance(document, Level)
            else Scene.from_dict(data)
        )
        project.save_document(duplicate, relative)
        if isinstance(duplicate, World):
            window._engine.set_scene(None)
            window._engine.set_world(
                duplicate,
                project=project,
                world_resource_path=relative,
            )
        else:
            window._engine.set_scene(duplicate)
        document_path = project.document_file(relative)
        window._active_document.open(duplicate, document_path)
        window._last_save_path = document_path
        window._selected_ids = ()
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Duplicated scene as: {relative}")
        window._present_all()

    def run_project(self) -> None:
        """Launch the project's Python entry point independently of the edit scene."""
        window = self.window
        project = window._engine.project
        if project is None:
            return
        if not self._project_process_controller.prepare_start():
            return
        try:
            script = self._script_entry_point_path(project)
        except (OSError, ProjectError, ValueError) as exc:
            window._console.log(
                project_messages.project_script_start_failed(
                    project.script_entry_point, project.entrypoint, str(exc)
                ),
                level="error",
            )
            messagebox.showerror("Run Project", str(exc), parent=window._root)
            return
        if not script.is_file():
            error = project_messages.project_script_entrypoint_missing(project.script_entry_point)
            window._console.log(
                project_messages.project_script_start_failed(
                    project.script_entry_point, project.entrypoint, error
                ),
                level="error",
            )
            messagebox.showerror(
                "Run Project",
                error,
                parent=window._root,
            )
            return
        self._project_process_controller.start(project, script)

    @staticmethod
    def _script_entry_point_path(project: Project) -> Path:
        entry_point = project.script_entry_point
        if not isinstance(entry_point, str) or not entry_point.strip():
            raise ProjectError(project_messages.project_script_entrypoint_required())
        candidate = Path(entry_point)
        windows_candidate = PureWindowsPath(entry_point)
        if (
            candidate.is_absolute()
            or windows_candidate.is_absolute()
            or windows_candidate.drive
            or ".." in candidate.parts
            or ".." in windows_candidate.parts
        ):
            raise ProjectError(project_messages.project_script_entrypoint_outside_project())
        project_root = project.path.resolve()
        script = (project_root / candidate).resolve()
        try:
            script.relative_to(project_root)
        except ValueError as error:
            raise ProjectError(
                project_messages.project_script_entrypoint_escapes_project()
            ) from error
        return script

    def stop_project(self) -> None:
        """Terminate a child launched by Run Project, if it is still alive."""
        self._project_process_controller.stop()

    def restore_after_run_project(self) -> None:
        """Undo ``run_project``'s scene swap once the run has stopped."""
        if self._pending_restore is None:
            return
        scene, last_save_path = self._pending_restore
        self._pending_restore = None
        window = self.window
        window._engine.set_scene(scene)
        window._last_save_path = last_save_path
        window._root.title(self.window_title())
        window._console.log("[Editor] Restored previous scene after Run Project")
        window._present_all()
