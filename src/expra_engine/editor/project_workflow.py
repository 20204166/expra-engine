"""Editor bridge for the headless canonical Project workflow."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
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
from expra_engine.editor.world_authoring import WorldAuthoringWorkflow
from expra_engine.messages import project as project_messages
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_registry import ScriptRegistry

_PROJECT_POLL_INTERVAL_MS = 100
_PROJECT_OUTPUT_TAIL_BYTES = 8192
_PROJECT_OUTPUT_MAX_CHARS = 2048


class ProjectWorkflow:
    """Keep project dialogs and switching policy outside the editor shell."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self._pending_restore: tuple[Any, Path | None] | None = None
        self._project_process: subprocess.Popen[bytes] | None = None
        self._project_poll_id: str | None = None
        self._project_output_file: Any | None = None
        self._project_script_path: Path | None = None
        self._project_document_entrypoint: str | None = None
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
        active_document = getattr(window, "_active_document", None)
        if active_document is not None:
            active_document.open(None)
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
        active_document = getattr(window, "_active_document", None)
        dirty = (
            active_document.is_dirty
            if active_document is not None
            else getattr(window._command_stack, "is_dirty", window._command_stack.can_undo)
        )
        if not dirty:
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
        active_document = getattr(window, "_active_document", None)
        if active_document is not None:
            active_document.open(document, project.document_file())
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
        document = _active_document_value(window)
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
        active_document = getattr(window, "_active_document", None)
        if active_document is not None:
            active_document.open(document, document_path)
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
        active_document = getattr(window, "_active_document", None)
        if active_document is not None:
            active_document.open(document, document_path)
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
        document = _active_document_value(window)
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
            _mark_active_document_saved(window, target)
            window._console.log(f"[Editor] Scene saved as: {target}")
            return
        try:
            relative = target.resolve().relative_to(project.path.resolve()).as_posix()
            project.save_document(document, relative)
        except (OSError, ProjectError, ValueError) as exc:
            messagebox.showerror("Save Scene As", str(exc), parent=window._root)
            return
        window._last_save_path = project.document_file(relative)
        _mark_active_document_saved(window, window._last_save_path)
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Scene saved as: {relative}")

    def save_scene(self) -> None:
        """Compatibility wrapper for the active typed-document Save action."""
        self.save_active_document()

    def save_active_document(self) -> None:
        window = self.window
        document = _active_document_value(window)
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
            _mark_active_document_saved(window, window._last_save_path)
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
        document = _active_document_value(window)
        if window._last_save_path is None or document is None:
            return
        project = window._engine.project
        if project is None:
            if isinstance(document, World):
                raise ProjectError("World documents must be saved through their Project")
            window._last_save_path.write_text(
                json.dumps(document.to_dict(), indent=2), encoding="utf-8"
            )
            _mark_active_document_saved(window, window._last_save_path)
            return
        relative = window._last_save_path.resolve().relative_to(project.path).as_posix()
        if relative.casefold().endswith(".json"):
            mapping = project.migrate_to_protobuf()
            relative = mapping.get(relative, relative)
            window._last_save_path = project.document_file(relative)
            window._console.log("[Editor] Migrated legacy JSON documents to canonical PB")
        project.save_document(document, relative)
        _mark_active_document_saved(window, window._last_save_path)

    def duplicate_scene(self, name: str | None = None) -> None:
        """Compatibility wrapper for typed active-document duplication."""
        self.duplicate_document(name)

    def duplicate_document(self, name: str | None = None) -> None:
        """Duplicate the active document while preserving referenced Level paths."""
        window = self.window
        project = window._engine.project
        document = _active_document_value(window)
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
        active_document = getattr(window, "_active_document", None)
        if active_document is not None:
            active_document.open(duplicate, document_path)
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
        process = self._project_process
        if process is not None:
            try:
                return_code = process.poll()
            except OSError as exc:
                window._console.log(
                    f"[Editor] Could not check project process: {exc}", level="error"
                )
                return
            if return_code is None:
                return
            self._report_project_exit(return_code)
            self._forget_project_process(process)
            self._close_project_output()
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
        # The workflow owns this file until the launched child exits.
        output_file = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
        try:
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=project.path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=output_file,
            )
        except OSError as exc:
            output_file.close()
            window._console.log(
                project_messages.project_launch_failed(str(script), project.entrypoint, str(exc)),
                level="error",
            )
            messagebox.showerror("Run Project", str(exc), parent=window._root)
            return
        self._project_process = process
        self._project_output_file = output_file
        self._project_script_path = script
        self._project_document_entrypoint = project.entrypoint
        if not self._schedule_project_poll(process):
            try:
                self.stop_project()
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                detail = f"Could not monitor project process; stopping it also failed: {stop_error}"
            else:
                detail = "Could not monitor project process; it was stopped."
            messagebox.showerror("Run Project", detail, parent=window._root)
            return
        window._console.log(
            project_messages.project_started(
                project.script_entry_point,
                project.entrypoint,
            )
        )

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

    def _schedule_project_poll(self, process: subprocess.Popen[bytes]) -> bool:
        if self._project_process is not process:
            return False
        timer = getattr(self.window, "_timer", None)
        if timer is None:
            return False
        try:
            identifier = timer.schedule(
                _PROJECT_POLL_INTERVAL_MS,
                self._poll_project_process,
                process,
            )
        except Exception:  # noqa: BLE001
            return False
        if identifier is None:
            return False
        self._project_poll_id = identifier
        return True

    def _poll_project_process(self, process: subprocess.Popen[bytes]) -> None:
        if self._project_process is not process:
            return
        self._project_poll_id = None
        try:
            return_code = process.poll()
        except OSError as error:
            try:
                self.stop_project()
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                self.window._console.log(
                    f"[Editor] Could not poll project process ({error}) or stop it ({stop_error}).",
                    level="error",
                )
            else:
                self.window._console.log(
                    f"[Editor] Stopped project after process polling failed: {error}",
                    level="error",
                )
            return
        if return_code is not None:
            self._report_project_exit(return_code)
            self._forget_project_process(process)
            self._close_project_output()
            return
        if not self._schedule_project_poll(process):
            try:
                self.stop_project()
            except (OSError, subprocess.TimeoutExpired) as error:
                self.window._console.log(
                    f"[Editor] Could not monitor or stop project process: {error}",
                    level="error",
                )
            else:
                self.window._console.log(
                    "[Editor] Stopped project because process monitoring became unavailable.",
                    level="error",
                )

    def _report_project_exit(self, return_code: int) -> None:
        level = "info" if return_code == 0 else "error"
        detail = self._read_project_output_tail() if return_code != 0 else ""
        self.window._console.log(
            project_messages.project_exited(
                return_code,
                str(self._project_script_path or "(unknown)"),
                self._project_document_entrypoint,
                detail,
            ),
            level=level,
        )

    def _read_project_output_tail(self) -> str:
        output_file = self._project_output_file
        if output_file is None:
            return ""
        try:
            output_file.flush()
            output_file.seek(0, 2)
            size = output_file.tell()
            output_file.seek(max(0, size - _PROJECT_OUTPUT_TAIL_BYTES))
            data = output_file.read(_PROJECT_OUTPUT_TAIL_BYTES)
        except (OSError, ValueError):
            return ""
        text = data.decode("utf-8", errors="replace").strip()
        if len(text) > _PROJECT_OUTPUT_MAX_CHARS:
            text = text[-_PROJECT_OUTPUT_MAX_CHARS:]
        return text

    def _close_project_output(self) -> None:
        output_file = self._project_output_file
        self._project_output_file = None
        self._project_script_path = None
        self._project_document_entrypoint = None
        if output_file is not None:
            with contextlib.suppress(OSError):
                output_file.close()

    def _cancel_project_poll(self) -> None:
        identifier = self._project_poll_id
        self._project_poll_id = None
        timer = getattr(self.window, "_timer", None)
        if identifier is not None and timer is not None:
            timer.cancel(identifier)

    def _forget_project_process(self, process: subprocess.Popen[bytes]) -> None:
        if self._project_process is not process:
            return
        self._project_process = None
        self._cancel_project_poll()

    @staticmethod
    def _process_exited(process: subprocess.Popen[bytes]) -> bool:
        try:
            return process.poll() is not None
        except OSError:
            return False

    def stop_project(self) -> None:
        """Terminate a child launched by Run Project, if it is still alive."""
        process = self._project_process
        self._cancel_project_poll()
        if process is None:
            self._close_project_output()
            return
        try:
            return_code = process.poll()
        except OSError:
            return_code = None
        if return_code is not None:
            self._report_project_exit(return_code)
            self._forget_project_process(process)
            self._close_project_output()
            return
        try:
            process.terminate()
        except OSError:
            if self._process_exited(process):
                self._forget_project_process(process)
                self._close_project_output()
                return
            self._schedule_project_poll(process)
            raise
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                if self._process_exited(process):
                    self._forget_project_process(process)
                    self._close_project_output()
                    return
                self._schedule_project_poll(process)
                raise
        except OSError:
            if self._process_exited(process):
                self._forget_project_process(process)
                self._close_project_output()
                return
            self._schedule_project_poll(process)
            raise
        self._forget_project_process(process)
        self._close_project_output()

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


def _active_document_value(window: Any) -> Scene | World | None:
    session = getattr(window, "_active_document", None)
    if session is not None:
        return session.document
    return getattr(window._engine, "edit_scene", None)


def _mark_active_document_saved(window: Any, path: Path | None) -> None:
    session = getattr(window, "_active_document", None)
    if session is not None:
        session.mark_saved(path)
        return
    command_stack = getattr(window, "_command_stack", None)
    if command_stack is not None:
        mark_clean = getattr(command_stack, "mark_clean", None)
        if callable(mark_clean):
            mark_clean()
