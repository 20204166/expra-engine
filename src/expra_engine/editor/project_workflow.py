"""Editor bridge for the headless canonical Project workflow."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Scene
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_registry import ScriptRegistry


class ProjectWorkflow:
    """Keep project dialogs and switching policy outside the editor shell."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self._pending_restore: tuple[Any, Path | None] | None = None

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
        scene = project.load_scene()
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
        window._last_save_path = project.scene_file()
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
        suffix = " (main)" if relative == project.start_scene else ""
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
                filetypes=[("Scene files", "*.json")],
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
            scene = project.load_scene(relative_path)
        except ProjectError as exc:
            messagebox.showerror("Open Scene", str(exc), parent=window._root)
            return
        window._engine.set_scene(scene)
        window._last_save_path = project.scene_file(relative_path)
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
        path = filedialog.asksaveasfilename(
            title="Save Scene As",
            defaultextension=".json",
            filetypes=[("Scene files", "*.json")],
            initialdir=str(project.scenes_dir) if project is not None else None,
        )
        if not path:
            return
        window._last_save_path = Path(path)
        if project is None:
            window._last_save_path.write_text(
                json.dumps(scene.to_dict(), indent=2), encoding="utf-8"
            )
            window._console.log(f"[Editor] Scene saved as: {window._last_save_path}")
            return
        try:
            relative = window._last_save_path.resolve().relative_to(project.path).as_posix()
        except ValueError:
            messagebox.showerror(
                "Save Scene As", "Scene must be saved inside the project.", parent=window._root
            )
            return
        project.save_scene(scene, relative)
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Scene saved as: {relative}")

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
        relative = f"scenes/{Path(name).stem}.json"
        if project.scene_file(relative).exists():
            messagebox.showerror(
                "Duplicate Scene", f"Scene already exists: {relative}", parent=window._root
            )
            return
        data = scene.to_dict()
        data["scene_id"] = str(uuid.uuid4())
        data["name"] = name
        duplicate = Scene.from_dict(data)
        project.save_scene(duplicate, relative)
        window._engine.set_scene(duplicate)
        window._last_save_path = project.scene_file(relative)
        window._selected_ids = ()
        window._root.title(self.window_title())
        window._console.log(f"[Editor] Duplicated scene as: {relative}")
        window._present_all()

    def run_project(self) -> None:
        """Play from the project's start scene, restoring the prior scene on Stop."""
        window = self.window
        project = window._engine.project
        if project is None or project.start_scene is None:
            window._act_play()
            return
        if self._current_relative_path(project) == project.start_scene:
            window._act_play()
            return
        try:
            start_scene = project.load_scene(project.start_scene)
        except ProjectError as exc:
            messagebox.showerror("Run Project", str(exc), parent=window._root)
            return
        self._pending_restore = (window._engine.edit_scene, window._last_save_path)
        window._engine.set_scene(start_scene)
        window._last_save_path = project.scene_file(project.start_scene)
        window._act_play()

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
