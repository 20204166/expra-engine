"""Real Qt editor integration for first-class World documents."""

from pathlib import Path
from unittest.mock import patch

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from tests.support.qt_editor import make_editor, pump


def test_real_editor_opens_world_as_metadata_hierarchy_and_viewport(tmp_path: Path) -> None:
    project = Project.create("World Editor", tmp_path / "project")
    level = Level("Town")
    project.save_document(level, "levels/town.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor(
                "town",
                "levels/town.level.pb",
                origin=(0.0, 0.0),
                bounds=(-50.0, -50.0, 100.0, 100.0),
            ),
        ),
        initial_level_id="town",
    )
    project.save_document(world, "worlds/main.world.pb")
    window = make_editor(Engine())
    try:
        window._project_workflow.open_loaded(project)
        asset = AssetEntry(
            project.document_file("worlds/main.world.pb"),
            "main.world.pb",
            False,
            ResourceId.from_project_path("worlds/main.world.pb", scheme="project"),
        )
        window._on_asset_open(asset)
        pump(window)

        assert window._active_document.document == world
        assert window._active_document.kind.value == "world"
        assert window._hierarchy._tree.exists("level:town")
        assert window._viewport._canvas.find_withtag("world:level:town")
        assert window._inspector._header_label.text() == "WORLD INSPECTOR"
        assert window._engine.world_streaming_system is not None
        assert window._engine.world_streaming_system.state("town").state.value == "unloaded"

        window._on_hierarchy_select(("level:town",))
        pump(window)
        assert window._inspector._world_origin_x_var is not None
        assert window._inspector._world_origin_y_var is not None
        window._inspector._world_origin_x_var.set("25")
        window._inspector._world_origin_y_var.set("10")
        window._inspector._apply_world_placement()
        updated_world = window._active_document.document
        assert updated_world.levels[0].origin == (25.0, 10.0)
        assert window._active_document.is_dirty

        window._project_workflow.save_scene_silent()
        assert not window._active_document.is_dirty
        assert project.load_world("worlds/main.world.pb") == updated_world
    finally:
        window._on_close()


def test_real_editor_new_dropdown_and_save_label_follow_typed_document_kind(
    tmp_path: Path,
) -> None:
    project = Project.create("Typed Documents", tmp_path / "project")
    window = make_editor(Engine())
    try:
        window._project_workflow.open_loaded(project)
        new_button = window._toolbar.action_buttons["New ▼"]
        new_actions = new_button.menu().actions()
        save_button = window._toolbar.action_buttons["save_document"]

        assert len(new_actions) == 3
        assert save_button.text() == "Save Scene"
        assert window._save_action.text() == "Save Scene"
        assert window._save_as_action.text() == "Save Scene As..."
        assert "SCENE" in window.windowTitle()
        with patch.object(
            window._project_workflow._dialogs, "ask_string", return_value="Forest"
        ):
            new_actions[1].trigger()
        assert window._active_document.kind.value == "level"
        assert save_button.text() == "Save Level"
        assert window._save_action.text() == "Save Level"
        assert window._save_as_action.text() == "Save Level As..."
        assert "LEVEL" in window.windowTitle()
        assert project.document_file("levels/Forest.level.pb").is_file()

        with patch.object(
            window._project_workflow._dialogs, "ask_string", return_value="Main World"
        ):
            new_actions[2].trigger()
        assert window._active_document.kind.value == "world"
        assert save_button.text() == "Save World"
        assert window._save_action.text() == "Save World"
        assert window._save_as_action.text() == "Save World As..."
        assert "WORLD" in window.windowTitle()
        assert project.document_file("worlds/Main World.world.pb").is_file()
        assert window._actions.is_enabled("add_entity") is False
        assert window._actions.is_enabled("add_world_level") is True

        with patch.object(
            window._project_workflow._dialogs, "ask_string", return_value="Props"
        ):
            new_actions[0].trigger()
        assert window._active_document.kind.value == "scene"
        assert save_button.text() == "Save Scene"
        assert project.document_file("scenes/Props.scene.pb").is_file()
    finally:
        window._on_close()
