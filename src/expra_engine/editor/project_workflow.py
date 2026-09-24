"""Editor bridge for the headless canonical Project workflow."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any

from expra_engine.core.project import Project, ProjectError
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_registry import ScriptRegistry


class ProjectWorkflow:
    """Keep project dialogs and switching policy outside the editor shell."""

    def __init__(self, window: Any) -> None:
        self.window = window

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
        window._engine.set_project(None)
        window._engine.set_scene(None)
        window._viewport.set_resource_service(None)
        window._editor_context = replace(window._editor_context, project=None)
        window._command_stack.clear()
        window._selected_id = None
        window._actions.set_enabled("close_project", False)
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
        window._viewport.set_resource_service(
            project.resource_service(observer=window._observer)
        )
        window._engine.set_script_registry(ScriptRegistry(project.path))
        window._editor_context = replace(window._editor_context, project=project)
        window._command_stack.clear()
        window._assets.set_root_directory(project.assets_dir)
        recent = [str(project.path), *window._preferences.recent_projects]
        window._preferences = replace(
            window._preferences,
            recent_projects=tuple(dict.fromkeys(recent))[:10],
        )
        window._selected_id = None
        window._last_save_path = project.scene_file()
        window._root.title(f"{project.name} — Expra Editor")
        window._update_project_actions()
        window._console.log(f"[Editor] Opened project: {project.name}")
        window._present_all()
