"""World authoring integration tests against the canonical Qt editor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.level_anchor import LevelAnchorComponent

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _anchor(level: Level, name: str, anchor_id: str, kind: str) -> None:
    entity = level.create_entity(name)
    entity.add_component(TransformComponent())
    entity.add_component(LevelAnchorComponent(anchor_id, kind=kind))


def _project(root: Path) -> Project:
    project = Project.create("WorldParity", root)
    town = Level("Town")
    _anchor(town, "East Gate", "east", "exit")
    project.save_document(town, "levels/town.level.pb")
    field = Level("Field")
    _anchor(field, "West Gate", "west", "entrance")
    project.save_document(field, "levels/field.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb", origin=(0.0, 0.0), bounds=(-20.0, -20.0, 40.0, 40.0)),
        ),
        initial_level_id="town",
    )
    project.save_document(world, "worlds/main.world.pb")
    return project


def _open_world(frontend, window, tmp_path):
    project = _project(tmp_path / "project")
    w = window()
    w._project_workflow.open_loaded(Project.load(project.path))
    entry = AssetEntry(
        project.document_file("worlds/main.world.pb"),
        "main.world.pb",
        False,
        ResourceId.from_project_path("worlds/main.world.pb", scheme="project"),
    )
    w._on_asset_open(entry)
    frontend.pump(w)
    return project, w


def _rows(w) -> list[str]:
    return [w._hierarchy._tree.item(i, "text") for i in w._hierarchy._row_state]


def test_world_document_opens_with_world_hierarchy_inspector_and_viewport(
    frontend, window, tmp_path
) -> None:
    _, w = _open_world(frontend, window, tmp_path)
    assert w._active_document.kind.value == "world"
    assert _rows(w) == ["Main", "Levels", "town — levels/town.level.pb [Initial]", "Connections"]
    assert w._viewport._world is not None
    assert w._viewport._canvas.find_withtag("world:level:town")
    assert w._inspector._header_label is not None
    assert w._actions.is_enabled("add_world_level") is True
    assert w._actions.is_enabled("add_entity") is False
    assert w._engine.world_streaming_system is not None

    w._on_hierarchy_select(("level:town",))
    frontend.pump(w)
    assert w._selected_ids == ("level:town",)
    assert w._inspector._world_selected_level_id == "town"
    assert w._inspector._world_origin_x_var.get() == "0.0"
    assert w._actions.is_enabled("delete_entity") is False


def test_add_level_connection_initial_placement_and_removal(frontend, window, tmp_path) -> None:
    project, w = _open_world(frontend, window, tmp_path)
    dialogs = frontend.dialogs(w)

    with patch.object(
        dialogs, "ask_open_file", return_value=str(project.document_file("levels/field.level.pb"))
    ):
        w._act_add_world_level()
    frontend.pump(w)
    assert [d.instance_id for d in w._active_document.document.levels] == ["town", "field"]
    assert w._active_document.is_dirty

    answers = iter(["town", "east", "field", "west", "seamless"])
    with patch.object(dialogs, "ask_string", side_effect=lambda *a, **k: next(answers)):
        w._act_create_world_connection()
    frontend.pump(w)
    world = w._active_document.document
    assert len(world.connections) == 1
    connection = world.connections[0]
    assert (connection.source_level_id, connection.destination_level_id) == ("town", "field")
    rows = _rows(w)
    assert any("town.east → field.west [seamless]" in row for row in rows)

    w._on_world_set_initial_level("field")
    frontend.pump(w)
    assert w._active_document.document.initial_level_id == "field"
    w._on_world_level_placement("field", (30.0, 4.0))
    frontend.pump(w)
    assert next(d for d in w._active_document.document.levels if d.instance_id == "field").origin == (30.0, 4.0)

    w._on_hierarchy_select((f"connection:{connection.connection_id}",))
    frontend.pump(w)
    assert w._inspector._world_render_key is not None
    w._on_world_remove_item(f"connection:{connection.connection_id}")
    frontend.pump(w)
    assert w._active_document.document.connections == ()

    w._act_undo()
    frontend.pump(w)
    assert len(w._active_document.document.connections) == 1
    w._act_save_document()
    frontend.pump(w)
    saved = Project.load(project.path).load_document("worlds/main.world.pb")
    assert [d.instance_id for d in saved.levels] == ["town", "field"]
    assert saved.initial_level_id == "field"
    assert len(saved.connections) == 1


def test_viewport_level_click_selects_and_row_activation_opens_the_level(
    frontend, window, tmp_path
) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []
    _, w = _open_world(frontend, window, tmp_path)
    original = w._viewport._on_entity_click
    w._viewport._on_entity_click = lambda ids, extend: (calls.append((ids, extend)), original(ids, extend))[1]
    canvas = w._viewport._canvas
    canvas.tag_bind(
        "level:town", "<Button-1>", lambda _e: w._viewport._on_entity_click(("level:town",), False)
    )
    w._on_hierarchy_select(("level:town",))
    frontend.pump(w)
    assert w._selected_ids == ("level:town",)

    w._hierarchy._on_tree_activate()
    frontend.pump(w)
    assert w._active_document.kind.value == "level"
    assert "levels/town.level.pb" in frontend.title(w)


def test_dropping_a_level_asset_on_the_world_viewport_adds_it_at_the_drop_point(
    frontend, window, tmp_path
) -> None:
    project, w = _open_world(frontend, window, tmp_path)
    canvas = w._viewport._canvas
    field = AssetEntry(
        project.document_file("levels/field.level.pb"),
        "field.level.pb",
        False,
        ResourceId.from_project_path("levels/field.level.pb", scheme="project"),
    )
    assert field.kind == "Level"
    origin_x, origin_y = canvas.global_origin()
    expected = w._viewport._camera.unproject((200.0, 150.0))
    w._on_asset_drop(field, origin_x + 200, origin_y + 150)
    frontend.pump(w)
    levels = w._active_document.document.levels
    assert [d.instance_id for d in levels] == ["town", "field"]
    origin = levels[1].origin
    assert origin == pytest.approx(expected, abs=1e-6)
