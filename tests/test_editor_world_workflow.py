"""Real Tk editor integration for first-class World documents."""

from pathlib import Path
from unittest.mock import patch

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from expra_engine.ui.editor_window import EditorWindow


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
    window = EditorWindow(Engine())
    try:
        window._project_workflow.open_loaded(project)
        asset = AssetEntry(
            project.document_file("worlds/main.world.pb"),
            "main.world.pb",
            False,
            ResourceId.from_project_path("worlds/main.world.pb", scheme="project"),
        )
        window._on_asset_open(asset)
        window._root.update()

        assert window._active_document.document == world
        assert window._active_document.kind.value == "world"
        assert window._hierarchy._tree.exists("level:town")
        assert window._viewport._canvas.find_withtag("world:level:town")
        assert window._inspector._header_label.cget("text") == "WORLD INSPECTOR"
        assert window._engine.world_streaming_system is not None
        assert window._engine.world_streaming_system.state("town").state.value == "unloaded"

        window._on_hierarchy_select(("level:town",))
        window._root.update()
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
    window = EditorWindow(Engine())
    try:
        window._project_workflow.open_loaded(project)
        new_button = window._toolbar.action_buttons["New ▼"]
        new_menu = new_button.nametowidget(new_button.cget("menu"))
        save_button = window._toolbar.action_buttons["save_document"]

        assert new_menu.index("end") == 2
        assert save_button.cget("text") == "Save Scene"
        assert window._file_menu.entrycget(window._save_menu_index, "label") == "Save Scene"
        assert window._file_menu.entrycget(window._save_as_menu_index, "label") == "Save Scene As..."
        assert "SCENE" in window._root.title()
        with patch(
            "expra_engine.editor.project_workflow.simpledialog.askstring",
            return_value="Forest",
        ):
            new_menu.invoke(1)
        assert window._active_document.kind.value == "level"
        assert save_button.cget("text") == "Save Level"
        assert window._file_menu.entrycget(window._save_menu_index, "label") == "Save Level"
        assert window._file_menu.entrycget(window._save_as_menu_index, "label") == "Save Level As..."
        assert "LEVEL" in window._root.title()
        assert project.document_file("levels/Forest.level.pb").is_file()

        with patch(
            "expra_engine.editor.project_workflow.simpledialog.askstring",
            return_value="Main World",
        ):
            new_menu.invoke(2)
        assert window._active_document.kind.value == "world"
        assert save_button.cget("text") == "Save World"
        assert window._file_menu.entrycget(window._save_menu_index, "label") == "Save World"
        assert window._file_menu.entrycget(window._save_as_menu_index, "label") == "Save World As..."
        assert "WORLD" in window._root.title()
        assert project.document_file("worlds/Main World.world.pb").is_file()
        assert window._actions.is_enabled("add_entity") is False
        assert window._actions.is_enabled("add_world_level") is True

        with patch(
            "expra_engine.editor.project_workflow.simpledialog.askstring",
            return_value="Props",
        ):
            new_menu.invoke(0)
        assert window._active_document.kind.value == "scene"
        assert save_button.cget("text") == "Save Scene"
        assert project.document_file("scenes/Props.scene.pb").is_file()
    finally:
        window._on_close()
