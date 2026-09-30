"""Script creation and attachment actions contributed to the editor shell."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from expra_engine.editor.script_tools import attach_script, create_behaviour_script
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry


class ScriptEditorActionsMixin:
    """New/attach/remove Behaviour script actions for EditorWindow."""

    # Provided by the concrete editor window.
    _assets: Any
    _console: Any
    _dialogs: Any
    _engine: Any
    _present_all: Any
    _selected_id: Any

    def _act_new_script(self) -> None:
        project = self._engine.project
        if project is None:
            self._dialogs.show_warning("New Script", "Open a project before creating scripts.")
            return
        relative_path = self._dialogs.ask_string("New Script", "Path under scripts/")
        class_name = self._dialogs.ask_string("New Script", "Behaviour class name")
        if not relative_path or not class_name:
            return
        try:
            resource = create_behaviour_script(project.path, f"scripts/{relative_path}", class_name)
        except (ValueError, FileExistsError) as exc:
            self._dialogs.show_error("New Script", str(exc))
            return
        self._console.log(f"[Editor] Created script: {resource}")
        self._assets.refresh()

    def _act_attach_script(self) -> None:
        if self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        if entity is None:
            return
        script_id = self._dialogs.ask_string("Attach Script", "project://scripts/example.py")
        class_name = self._dialogs.ask_string("Attach Script", "Behaviour class name")
        if not script_id or not class_name:
            return
        try:
            component = attach_script(entity, script_id, class_name)
            with contextlib.suppress(OSError, ImportError, AttributeError, TypeError, ValueError):
                project_root = self._engine.project.path if self._engine.project else Path.cwd()
                behaviour_type = ScriptRegistry(project_root).resolve(script_id, class_name)
                component.exposed_values = {
                    name: field.default for name, field in behaviour_type.exposed_schema().items()
                }
        except (ValueError, TypeError) as exc:
            self._dialogs.show_error("Attach Script", str(exc))
            return
        self._console.log(f"[Editor] Attached {class_name} to {entity.name}")
        self._present_all()

    def _act_remove_script(self) -> None:
        if self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        if entity is None:
            return
        scripts = [
            component for component in entity.components if isinstance(component, ScriptComponent)
        ]
        if scripts:
            entity.remove_component(scripts[-1])
            self._console.log(f"[Editor] Removed script from {entity.name}")
            self._present_all()
