"""Editor authoring boundary for linked Scene Instance descendants.

Generated descendants are resolved from a source Scene and omitted from compact
saves. These tests pin that editor mutations either persist (override routing /
Make Unique) or are rejected before they create undo/dirty state.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene, SceneInstanceComponent, resolve_scene_instances
from expra_engine.core.script_component import ScriptComponent
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.mutation_policy import MutationVerdict, decide_entity_mutation
from expra_engine.editor.project_workflow import ProjectWorkflow
from tests.support.qt_editor import QtEditorHarness

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _project_with_instance(root: Path) -> tuple[Project, str]:
    project = Project.create("Instance Authoring", root)
    source = Scene("Reusable")
    source_child = source.create_entity("Generated Child")
    source_child.add_component(TransformComponent(x=1.0))
    source_child.add_component(
        ScriptComponent(
            "project://scripts/door.py",
            "Door",
            exposed_values={"open_speed": 2.0},
        )
    )
    project.save_document(source, "scenes/source.scene.pb")

    owner = Scene("Owner")
    instance = owner.create_entity("Instance")
    instance.add_component(SceneInstanceComponent("scenes/source.scene.pb"))
    project.save_document(owner, "scenes/owner.scene.pb")
    return project, "scenes/owner.scene.pb"


def test_policy_distinguishes_authored_root_and_generated(tmp_path) -> None:
    scene = Scene("plain")
    authored = scene.create_entity("Authored")
    root = scene.create_entity("Instance")
    root.add_component(SceneInstanceComponent("scenes/source.scene.pb"))

    source = Scene("Source")
    source.create_entity("Generated Child").add_component(TransformComponent())
    resolve_scene_instances(scene, resolve_source=lambda _path: source)
    child = scene.find_entity_by_name("Generated Child")
    assert child is not None

    assert (
        decide_entity_mutation(scene, authored.entity_id, "transform").verdict
        is MutationVerdict.ALLOW_AUTHORED
    )
    assert (
        decide_entity_mutation(scene, root.entity_id, "transform").verdict
        is MutationVerdict.ALLOW_AUTHORED
    )
    assert (
        decide_entity_mutation(scene, child.entity_id, "transform").verdict
        is MutationVerdict.REJECT_LINKED
    )
    assert (
        decide_entity_mutation(scene, child.entity_id, "set_exposed_value").verdict
        is MutationVerdict.ROUTE_INSTANCE_OVERRIDE
    )


def test_editor_rejects_transient_child_transform_and_delete(tmp_path) -> None:
    with TemporaryDirectory() as directory:
        project, owner_path = _project_with_instance(Path(directory) / "project")
        editor = QtEditorHarness(Path(directory) / "prefs.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(project.path))
            window._project_workflow.open_document(owner_path)
            editor.pump(window)
            child = next(
                e for e in window._active_document.document.entities if e.name == "Generated Child"
            )
            window._on_hierarchy_select((child.entity_id,))
            editor.pump(window)

            window._on_transform_change(child.entity_id, "x", 99.0)
            editor.pump(window)
            assert child.get_component(TransformComponent).x == 1.0
            assert not window._command_stack.can_undo

            window._act_delete_entity()
            editor.pump(window)
            assert window._active_document.document.find_entity(child.entity_id) is not None
            assert not window._command_stack.can_undo
        finally:
            editor.close(window)


def test_script_edit_routes_to_instance_override_and_persists(tmp_path) -> None:
    with TemporaryDirectory() as directory:
        project, owner_path = _project_with_instance(Path(directory) / "project")
        editor = QtEditorHarness(Path(directory) / "prefs.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(project.path))
            window._project_workflow.open_document(owner_path)
            editor.pump(window)
            child = next(
                e for e in window._active_document.document.entities if e.name == "Generated Child"
            )
            window._on_hierarchy_select((child.entity_id,))
            editor.pump(window)

            window._on_script_value_change(child.entity_id, 1, "open_speed", 11.0)
            editor.pump(window)
            assert child.get_component(ScriptComponent).exposed_values["open_speed"] == 11.0
            instance = next(
                e for e in window._active_document.document.entities if e.name == "Instance"
            )
            override = instance.get_component(SceneInstanceComponent).overrides
            assert override == {"Generated Child": {"open_speed": 11.0}}

            window._act_save_document()
            editor.pump(window)
        finally:
            editor.close(window)

        reopened = Project.load(project.path).load_document(owner_path)
        reopened_child = next(e for e in reopened.entities if e.name == "Generated Child")
        assert reopened_child.get_component(ScriptComponent).exposed_values["open_speed"] == 11.0


def test_make_unique_detaches_source_and_persists_children(tmp_path) -> None:
    with TemporaryDirectory() as directory:
        project, owner_path = _project_with_instance(Path(directory) / "project")
        editor = QtEditorHarness(Path(directory) / "prefs.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(project.path))
            window._project_workflow.open_document(owner_path)
            editor.pump(window)
            instance = next(
                e for e in window._active_document.document.entities if e.name == "Instance"
            )
            window._on_hierarchy_select((instance.entity_id,))
            editor.pump(window)

            window._act_make_instance_unique()
            editor.pump(window)
            assert instance.get_component(SceneInstanceComponent) is None
            assert (
                window._active_document.document.find_entity_by_name("Generated Child") is not None
            )

            window._act_save_document()
            editor.pump(window)
        finally:
            editor.close(window)

        reopened = Project.load(project.path).load_document(owner_path)
        reopened_instance = next(e for e in reopened.entities if e.name == "Instance")
        assert reopened_instance.get_component(SceneInstanceComponent) is None
        assert any(e.name == "Generated Child" for e in reopened.entities)


def test_manual_save_maps_failure_to_dialog_and_keeps_dirty(tmp_path) -> None:
    project = Project.create("Save Error", tmp_path / "project")
    scene = Scene("Main")
    project.save_document(scene, "scenes/main.scene.pb")
    document = project.load_document("scenes/main.scene.pb")

    active_document = ActiveDocument()
    active_document.open(document, project.document_file("scenes/main.scene.pb"))
    active_document.mark_dirty()
    dialogs = MagicMock()
    window = SimpleNamespace(
        _engine=SimpleNamespace(project=project),
        _active_document=active_document,
        _last_save_path=project.document_file("scenes/main.scene.pb"),
        _console=MagicMock(),
        _dialogs=dialogs,
    )
    workflow = ProjectWorkflow(window)

    with patch.object(project, "save_document", side_effect=OSError("disk full")):
        workflow.save_active_document()

    dialogs.show_error.assert_called_once()
    assert active_document.is_dirty


def test_reparent_into_generated_child_is_rejected(tmp_path) -> None:
    from expra_engine.editor.interactions import reparent_selection_to

    with TemporaryDirectory() as directory:
        project, owner_path = _project_with_instance(Path(directory) / "project")
        editor = QtEditorHarness(Path(directory) / "prefs.json")
        window = editor.make(Engine())
        try:
            window._project_workflow.open_loaded(Project.load(project.path))
            window._project_workflow.open_document(owner_path)
            editor.pump(window)
            scene = window._active_document.document
            child = next(e for e in scene.entities if e.name == "Generated Child")
            authored = scene.create_entity("Authored")

            reparent_selection_to(window, (authored.entity_id,), child.entity_id)
            editor.pump(window)
            assert authored.parent_id is None
            assert not window._command_stack.can_undo
        finally:
            editor.close(window)
