"""Editor save/reopen round trips for Scene, Level and World documents.

The Qt editor saves through the canonical ``Project`` codec: a document edited and saved in
one editor session reopens intact in the next, and an unedited save is byte-identical to the
codec's own output (the editor adds no format of its own).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Level, Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from tests.support.qt_editor import QtEditorHarness

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _make_project(root: Path) -> Project:
    project = Project.create("Roundtrip", root)
    scene = Scene("Props")
    scene.create_entity("Crate").add_component(TransformComponent(x=3, y=4))
    project.save_document(scene, "scenes/props.scene.pb")
    level = Level("Town")
    level.create_entity("Well").add_component(TransformComponent(x=-2, y=1))
    project.save_document(level, "levels/town.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb", origin=(0.0, 0.0), bounds=(-50.0, -50.0, 100.0, 100.0)),
        ),
        initial_level_id="town",
    )
    project.save_document(world, "worlds/main.world.pb")
    return project


def _open(frontend, project: Project, relative: str):
    window = frontend.make(Engine())
    frontend.pump(window)
    window._project_workflow.open_loaded(Project.load(project.path))
    entry = AssetEntry(
        project.document_file(relative),
        Path(relative).name,
        False,
        ResourceId.from_project_path(relative, scheme="project"),
    )
    window._on_asset_open(entry)
    frontend.pump(window)
    return window


def _names(window) -> list[str]:
    tree = window._hierarchy._tree
    return [tree.item(i, "text") for i in window._hierarchy._row_state]


def _edit_and_save_entities(frontend, project, relative, new_name) -> None:
    window = _open(frontend, project, relative)
    try:
        window._act_add_entity()
        frontend.pump(window)
        window._inspector._name_var.set(new_name)
        window._inspector._handle_rename()
        frontend.pump(window)
        window._act_save_document()
        frontend.pump(window)
        assert not window._active_document.is_dirty
    finally:
        frontend.close(window)


def _entity_names(project: Project, relative: str) -> list[str]:
    return sorted(entity.name for entity in project.load_document(relative).entities)


@pytest.mark.parametrize(
    ("relative", "starting"),
    [("scenes/props.scene.pb", ["Crate"]), ("levels/town.level.pb", ["Well"])],
)
def test_scene_and_level_survive_repeated_editor_sessions(tmp_path, relative, starting) -> None:
    project = _make_project(tmp_path / "project")
    editor = QtEditorHarness(tmp_path / "prefs.json")

    _edit_and_save_entities(editor, project, relative, "FirstSession")
    assert _entity_names(Project.load(project.path), relative) == sorted([*starting, "FirstSession"])

    window = _open(editor, project, relative)
    try:
        assert sorted(_names(window)) == sorted([*starting, "FirstSession"])
    finally:
        editor.close(window)
    _edit_and_save_entities(editor, project, relative, "SecondSession")
    assert _entity_names(Project.load(project.path), relative) == sorted(
        [*starting, "FirstSession", "SecondSession"]
    )

    window = _open(editor, project, relative)
    try:
        assert sorted(_names(window)) == sorted([*starting, "FirstSession", "SecondSession"])
    finally:
        editor.close(window)


def test_world_placement_edit_survives_repeated_editor_sessions(tmp_path) -> None:
    project = _make_project(tmp_path / "project")
    editor = QtEditorHarness(tmp_path / "prefs.json")
    relative = "worlds/main.world.pb"

    window = _open(editor, project, relative)
    try:
        window._on_hierarchy_select(("level:town",))
        editor.pump(window)
        window._on_world_level_placement("town", (25.0, 10.0))
        editor.pump(window)
        window._act_save_document()
        editor.pump(window)
    finally:
        editor.close(window)
    assert Project.load(project.path).load_document(relative).levels[0].origin == (25.0, 10.0)

    window = _open(editor, project, relative)
    try:
        rows = [window._hierarchy._tree.item(i, "text") for i in window._hierarchy._row_state]
        assert rows == ["Main", "Levels", "town — levels/town.level.pb [Initial]", "Connections"]
        window._on_hierarchy_select(("level:town",))
        editor.pump(window)
        window._on_world_level_placement("town", (-7.5, 3.0))
        editor.pump(window)
        window._act_save_document()
        editor.pump(window)
    finally:
        editor.close(window)
    assert Project.load(project.path).load_document(relative).levels[0].origin == (-7.5, 3.0)


@pytest.mark.parametrize(
    "relative", ["scenes/props.scene.pb", "levels/town.level.pb", "worlds/main.world.pb"]
)
def test_editor_save_matches_the_project_codec_bytes(tmp_path, relative) -> None:
    source = _make_project(tmp_path / "source")
    via_editor = tmp_path / "via_editor"
    via_codec = tmp_path / "via_codec"
    shutil.copytree(source.path, via_editor)
    shutil.copytree(source.path, via_codec)

    editor = QtEditorHarness(tmp_path / "prefs.json")
    window = _open(editor, Project.load(via_editor), relative)
    try:
        window._act_save_document()
        editor.pump(window)
    finally:
        editor.close(window)

    codec_project = Project.load(via_codec)
    codec_project.save_document(codec_project.load_document(relative), relative)

    assert (via_editor / relative).read_bytes() == (via_codec / relative).read_bytes()
    assert (via_editor / "project.json").read_text() == (via_codec / "project.json").read_text()
