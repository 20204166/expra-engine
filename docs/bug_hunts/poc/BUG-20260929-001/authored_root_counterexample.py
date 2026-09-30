"""Check persistence of an authored Scene Instance root through the Qt editor."""

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


with TemporaryDirectory() as temporary:
    root = Path(temporary) / "project"
    project = Project.create("Authored root counterexample", root)
    source = Scene("Reusable")
    source.create_entity("Generated Child").add_component(TransformComponent(x=1.0))
    project.save_document(source, "scenes/source.scene.pb")

    owner = Scene("Owner")
    instance = owner.create_entity("Authored Instance Root")
    instance.add_component(TransformComponent(x=2.0))
    instance.add_component(SceneInstanceComponent("scenes/source.scene.pb"))
    project.save_document(owner, "scenes/owner.scene.pb")

    editor = QtEditorHarness(root.parent / "preferences.json")
    window = editor.make(Engine())
    try:
        window._project_workflow.open_loaded(Project.load(root))
        window._project_workflow.open_document("scenes/owner.scene.pb")
        editor.pump(window)
        root_entity = next(
            item for item in window._active_document.document.entities
            if item.name == "Authored Instance Root"
        )
        window._on_hierarchy_select((root_entity.entity_id,))
        editor.pump(window)
        position_x = window._inspector._component_widgets[(0, "x")]
        position_x.setFocus()
        position_x.selectAll()
        QTest.keyClicks(position_x, "9.5")
        QTest.keyClick(position_x, Qt.Key.Key_Return)
        editor.pump(window)
        edited_x = root_entity.get_component(TransformComponent).x
        window._act_save_document()
        editor.pump(window)
    finally:
        editor.close(window)

    reopened = Project.load(root).load_document("scenes/owner.scene.pb")
    saved_root = next(item for item in reopened.entities if item.name == "Authored Instance Root")
    saved_x = saved_root.get_component(TransformComponent).x
    saved_children = [item.name for item in reopened.entities if item.parent_id == saved_root.entity_id]
    print({"root_x_after_qt_edit": edited_x, "root_x_after_save_reopen": saved_x,
           "materialized_children_after_reopen": saved_children})
