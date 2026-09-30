"""Reproduce editor edits that have no authored target in a Scene Instance.

Run from the Expra checkout with ``.venv/bin/python``. All project files are
created inside temporary directories; no example or user project is modified.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.core.scene.scene_instance import SceneInstanceComponent
from tests.support.qt_editor import QtEditorHarness


def run_position_edit() -> tuple[float, float]:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "project"
        project = Project.create("Instance edit PoC", root)
        source = Scene("Reusable")
        source_entity = source.create_entity("Generated Child")
        source_entity.add_component(TransformComponent(x=1.0))
        project.save_document(source, "scenes/source.scene.pb")

        owner = Scene("Owner")
        instance = owner.create_entity("Instance")
        instance.add_component(SceneInstanceComponent("scenes/source.scene.pb"))
        project.save_document(owner, "scenes/owner.scene.pb")

        editor = QtEditorHarness(Path(temporary) / "preferences.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(root))
            window._project_workflow.open_document("scenes/owner.scene.pb")
            editor.pump(window)
            entity = next(
                item
                for item in window._active_document.document.entities
                if item.name == "Generated Child"
            )
            window._on_hierarchy_select((entity.entity_id,))
            editor.pump(window)

            position_x = window._inspector._component_widgets[(0, "x")]
            position_x.setFocus()
            position_x.selectAll()
            QTest.keyClicks(position_x, "9.5")
            QTest.keyClick(position_x, Qt.Key.Key_Return)
            editor.pump(window)
            edited_x = entity.get_component(TransformComponent).x

            QTest.mouseClick(
                window._toolbar.action_buttons["save_document"], Qt.MouseButton.LeftButton
            )
            editor.pump(window)
        finally:
            editor.close(window)

        reopened = Project.load(root).load_document("scenes/owner.scene.pb")
        reopened_child = next(item for item in reopened.entities if item.name == "Generated Child")
        saved_x = reopened_child.get_component(TransformComponent).x
        return edited_x, saved_x


def run_delete() -> tuple[bool, bool]:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "project"
        project = Project.create("Instance delete PoC", root)
        source = Scene("Reusable")
        source.create_entity("Generated Child").add_component(TransformComponent())
        project.save_document(source, "scenes/source.scene.pb")

        owner = Scene("Owner")
        instance = owner.create_entity("Instance")
        instance.add_component(SceneInstanceComponent("scenes/source.scene.pb"))
        project.save_document(owner, "scenes/owner.scene.pb")

        editor = QtEditorHarness(Path(temporary) / "preferences.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(root))
            window._project_workflow.open_document("scenes/owner.scene.pb")
            editor.pump(window)
            entity = next(
                item
                for item in window._active_document.document.entities
                if item.name == "Generated Child"
            )
            window._on_hierarchy_select((entity.entity_id,))
            editor.pump(window)
            window._act_delete_entity()
            editor.pump(window)
            present_after_delete = any(
                item.name == "Generated Child"
                for item in window._active_document.document.entities
            )
            window._act_save_document()
            editor.pump(window)
        finally:
            editor.close(window)

        reopened = Project.load(root).load_document("scenes/owner.scene.pb")
        present_after_reopen = any(item.name == "Generated Child" for item in reopened.entities)
        return present_after_delete, present_after_reopen


if __name__ == "__main__":
    edited_x, saved_x = run_position_edit()
    present_after_delete, present_after_reopen = run_delete()
    print(
        {
            "position_in_editor_after_real_qt_input": edited_x,
            "position_after_save_and_reopen": saved_x,
            "child_present_after_editor_delete": present_after_delete,
            "child_present_after_save_and_reopen": present_after_reopen,
        }
    )
