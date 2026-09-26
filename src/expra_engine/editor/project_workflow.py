"""Editor bridge for the headless canonical Project workflow."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Level, Scene
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_registry import ScriptRegistry

_PROJECT_POLL_INTERVAL_MS = 100


class ProjectWorkflow:
    """Keep project dialogs and switching policy outside the editor shell."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self._pending_restore: tuple[Any, Path | None] | None = None
        self._project_process: subprocess.Popen[bytes] | None = None
        self._project_poll_id: str | None = None

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
        if not window._command_stack.can_undo:
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
        scene = project.load_document(observer=window._observer)
        self.stop_project()
        runtime_preview = getattr(window, "_runtime_preview", None)
        if runtime_preview is not None:
            runtime_preview.stop()
        run_state = getattr(window._engine, "run_state", None)
        if getattr(run_state, "value", run_state) != "edit":
            window._engine.stop()
        window._engine.set_project(project)
        window._engine.set_scene(scene)
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
        """Expose the project's main scene and currently-edited scene (spec §22)."""
        window = self.window
        project = window._engine.project
        if project is None:
            return "Expra Editor"
        relative = self._current_relative_path(project)
        if relative is None:
            return f"{project.name} — Expra Editor"
        suffix = " (main)" if relative == project.entrypoint else ""
        return f"{project.name} — {relative}{suffix} — Expra Editor"

    def open_scene(self, relative_path: str | None = None) -> None:
        """Switch the edit scene to another scene already registered in the project."""
        window = self.window
        project = window._engine.project
        if project is None:
            return
        if relative_path is None:
            selected = filedialog.askopenfilename(
                title="Open Scene",
                initialdir=str(project.scenes_dir),
                filetypes=[
                    ("Scene documents", "*.scene.pb"),
                    ("Level documents", "*.level.pb"),
                    ("Legacy JSON", "*.json"),
                ],
            )
            if not selected:
                return
            try:
                relative_path = Path(selected).resolve().relative_to(project.path).as_posix()
            except ValueError:
                messagebox.showerror(
                    "Open Scene", "Scene must be inside the project.", parent=window._root
                )
                return
        if not self._confirm_switch():
            return
        try:
            scene = project.load_document(relative_path, observer=window._observer)
        except ProjectError as exc:
            messagebox.showerror("Open Scene", str(exc), parent=window._root)
            return
        window._engine.set_scene(scene)
        window._last_save_path = project.document_file(relative_path)
        window._selected_ids = ()
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Opened scene: {relative_path}")
        window._present_all()

    def save_scene_as(self) -> None:
        """Save the current edit scene to a new path, then keep editing it there."""
        window = self.window
        scene = window._engine.edit_scene
        if scene is None:
            messagebox.showwarning("Save Scene As", "No scene to save.", parent=window._root)
            return
        project = window._engine.project
        is_level = isinstance(scene, Level)
        extension = ".level.pb" if is_level else ".scene.pb"
        file_type = "Level documents" if is_level else "Scene documents"
        initial_dir = (
            (project.levels_dir if is_level else project.scenes_dir)
            if project is not None
            else None
        )
        path = filedialog.asksaveasfilename(
            title="Save Scene As",
            defaultextension=extension,
            filetypes=[(file_type, f"*{extension}"), ("Legacy JSON", "*.json")],
            initialdir=str(initial_dir) if initial_dir is not None else None,
        )
        if not path:
            return
        target = Path(path)
        if project is None:
            try:
                target.write_text(json.dumps(scene.to_dict(), indent=2), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Save Scene As", str(exc), parent=window._root)
                return
            window._last_save_path = target
            window._console.log(f"[Editor] Scene saved as: {target}")
            return
        try:
            relative = target.resolve().relative_to(project.path.resolve()).as_posix()
            project.save_document(scene, relative)
        except (OSError, ProjectError, ValueError) as exc:
            messagebox.showerror("Save Scene As", str(exc), parent=window._root)
            return
        window._last_save_path = project.document_file(relative)
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Scene saved as: {relative}")

    def save_scene(self) -> None:
        window = self.window
        scene = window._engine.edit_scene
        if scene is None:
            messagebox.showwarning("Save Scene", "No scene to save.")
            return
        project = window._engine.project
        if project is not None and window._last_save_path is not None:
            relative = window._last_save_path.resolve().relative_to(project.path)
            if relative.suffix.casefold() == ".json":
                mapping = project.migrate_to_protobuf()
                relative = Path(mapping.get(relative.as_posix(), relative.as_posix()))
                window._last_save_path = project.document_file(relative.as_posix())
                window._console.log("[Editor] Migrated legacy JSON documents to canonical PB")
            project.save_document(scene, relative.as_posix())
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
        """Save to the last selected path without opening a dialog."""
        window = self.window
        if window._last_save_path is None or window._engine.edit_scene is None:
            return
        scene = window._engine.edit_scene
        project = window._engine.project
        if project is None:
            window._last_save_path.write_text(
                json.dumps(scene.to_dict(), indent=2), encoding="utf-8"
            )
            return
        relative = window._last_save_path.resolve().relative_to(project.path).as_posix()
        if relative.casefold().endswith(".json"):
            mapping = project.migrate_to_protobuf()
            relative = mapping.get(relative, relative)
            window._last_save_path = project.document_file(relative)
            window._console.log("[Editor] Migrated legacy JSON documents to canonical PB")
        project.save_document(scene, relative)

    def duplicate_scene(self, name: str | None = None) -> None:
        """Copy the current edit scene into a new, independent scene file."""
        window = self.window
        project = window._engine.project
        scene = window._engine.edit_scene
        if project is None or scene is None:
            return
        if name is None:
            name = simpledialog.askstring("Duplicate Scene", "New scene name:", parent=window._root)
        if not name:
            return
        if isinstance(scene, Level):
            relative = f"levels/{Path(name).stem}.level.pb"
        else:
            relative = f"scenes/{Path(name).stem}.scene.pb"
        if project.document_file(relative).exists():
            messagebox.showerror(
                "Duplicate Scene", f"Scene already exists: {relative}", parent=window._root
            )
            return
        data = scene.to_dict()
        data["scene_id"] = str(uuid.uuid4())
        data["name"] = name
        duplicate = Level.from_dict(data) if isinstance(scene, Level) else Scene.from_dict(data)
        project.save_document(duplicate, relative)
        window._engine.set_scene(duplicate)
        window._last_save_path = project.document_file(relative)
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
            self._forget_project_process(process)
            self._report_project_exit(return_code)
        try:
            script = self._script_entry_point_path(project)
        except (OSError, ProjectError, ValueError) as exc:
            messagebox.showerror("Run Project", str(exc), parent=window._root)
            return
        if not script.is_file():
            messagebox.showerror(
                "Run Project",
                f"Script entry point not found: {project.script_entry_point}",
                parent=window._root,
            )
            return
        try:
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=project.path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            messagebox.showerror("Run Project", str(exc), parent=window._root)
            return
        self._project_process = process
        if not self._schedule_project_poll(process):
            try:
                self.stop_project()
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                detail = f"Could not monitor project process; stopping it also failed: {stop_error}"
            else:
                detail = "Could not monitor project process; it was stopped."
            messagebox.showerror("Run Project", detail, parent=window._root)
            return
        window._console.log(f"[Editor] Started project: {project.script_entry_point}")

    @staticmethod
    def _script_entry_point_path(project: Project) -> Path:
        entry_point = project.script_entry_point
        if not isinstance(entry_point, str) or not entry_point.strip():
            raise ProjectError("project script entry point must be a non-empty relative path")
        candidate = Path(entry_point)
        windows_candidate = PureWindowsPath(entry_point)
        if (
            candidate.is_absolute()
            or windows_candidate.is_absolute()
            or windows_candidate.drive
            or ".." in candidate.parts
            or ".." in windows_candidate.parts
        ):
            raise ProjectError("project script entry point must remain inside the project")
        project_root = project.path.resolve()
        script = (project_root / candidate).resolve()
        try:
            script.relative_to(project_root)
        except ValueError as error:
            raise ProjectError("project script entry point escapes the project") from error
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
            self._forget_project_process(process)
            self._report_project_exit(return_code)
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
        status = "exited" if return_code == 0 else f"exited with status {return_code}"
        level = "info" if return_code == 0 else "error"
        self.window._console.log(f"[Editor] Project {status}", level=level)

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
            return
        if self._process_exited(process):
            self._forget_project_process(process)
            return
        try:
            process.terminate()
        except OSError:
            if self._process_exited(process):
                self._forget_project_process(process)
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
                    return
                self._schedule_project_poll(process)
                raise
        except OSError:
            if self._process_exited(process):
                self._forget_project_process(process)
                return
            self._schedule_project_poll(process)
            raise
        self._forget_project_process(process)

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
