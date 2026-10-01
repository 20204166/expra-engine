"""End-to-end editor-window scenarios against the real Qt editor (offscreen)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import EngineRunState
from expra_engine.core.project import Project

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

def _row_labels(window):
    tree = window._hierarchy._tree
    return [tree.item(iid, "text") for iid in window._hierarchy._row_state]


def test_startup_state(frontend, window) -> None:
    w = window()
    console = frontend.console_text(w)
    assert "[Editor] Expra Engine started" in console
    assert "[Editor] Loaded scene: Sample Scene" in console
    assert _row_labels(w) == ["[CAM] Camera", "[PLY] Player"]
    assert frontend.title(w).endswith("Expra Editor")
    assert list(w._toolbar.action_buttons) == [
        "play",
        "pause",
        "stop",
        "run_project",
        "New ▼",
        "save_document",
    ]
    assert frontend.button_text(w, "play") == "▶  Play"
    assert frontend.button_text(w, "save_document") == "Save Scene"
    assert w._actions.is_enabled("play") is True
    assert w._actions.is_enabled("stop") is False
    assert w._actions.is_enabled("delete_entity") is False
    assert w._engine.run_state == EngineRunState.EDIT


def test_file_menu_entries(frontend, window) -> None:
    w = window()
    assert frontend.file_menu_labels(w) == [
        "Open Recent",
        "Quit",
        "Run Project",
        "Export Game...",
        "New Project...",
        "Open Project...",
        "Open Project Manifest...",
        "Close Project",
        "Import Asset...",
        "Input Settings...",
        "New Scene — reusable composition",
        "New Behaviour Script...",
        "New Level — playable place",
        "New World — connected Levels",
        "Open Document...",
        "Save Scene",
        "Save Scene As...",
        "Duplicate Document...",
    ]
    assert set(w._shortcuts.registered_sequences()) == {
        "Ctrl+D",
        "Ctrl+Z",
        "Ctrl+Y",
    }


def test_file_menu_is_native_qt_and_dispatches_shared_actions(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMenu

    w = window()
    assert isinstance(w._file_menu, QMenu)
    calls: list[str] = []
    monkeypatch.setattr(w._actions, "dispatch", lambda action_id: calls.append(action_id) or True)
    save_action = next(action for action in w._file_menu.actions() if action.text() == "Save Scene")

    save_action.trigger()

    assert calls == ["save_document"]


def test_add_select_delete_undo_redo(frontend, window) -> None:
    w = window()
    w._act_add_entity()
    frontend.pump(w)
    assert len(w._hierarchy._row_state) == 3
    assert len(w._selected_ids) == 1
    new_id = w._selected_ids[0]
    assert w._hierarchy._tree.selection() == (new_id,)
    assert w._actions.is_enabled("delete_entity") is True
    assert w._actions.is_enabled("undo") is True

    w._act_delete_entity()
    frontend.pump(w)
    assert len(w._hierarchy._row_state) == 2
    assert w._selected_ids == ()
    assert w._actions.is_enabled("delete_entity") is False

    w._act_undo()
    frontend.pump(w)
    assert len(w._hierarchy._row_state) == 3
    w._act_redo()
    frontend.pump(w)
    assert len(w._hierarchy._row_state) == 2
    console = frontend.console_text(w)
    assert "[Editor] Created entity: Entity" in console
    assert "[Editor] Deleted entity: Entity" in console
    assert "[Edit] Undo:" in console


def test_hierarchy_selection_syncs_window_inspector_and_viewport(frontend, window) -> None:
    w = window()
    camera, player = list(w._hierarchy._row_state)
    w._on_hierarchy_select((player,))
    frontend.pump(w)
    assert w._selected_ids == (player,)
    assert w._hierarchy._tree.selection() == (player,)
    assert w._inspector._current_entity_id == player
    assert w._viewport._selected_id == player
    w._on_hierarchy_select((camera, player, "missing"))
    frontend.pump(w)
    assert w._selected_ids == (camera, player)
    assert w._actions.is_enabled("duplicate_selection") is True
    w._on_hierarchy_select(())
    frontend.pump(w)
    assert w._selected_ids == ()
    assert w._actions.is_enabled("delete_entity") is False


def test_inspector_edits_flow_through_the_shared_command_stack(frontend, window) -> None:
    w = window()
    player_id = list(w._hierarchy._row_state)[1]
    w._on_hierarchy_select((player_id,))
    frontend.pump(w)
    inspector = w._inspector
    inspector._name_var.set("Hero")
    inspector._handle_rename()
    frontend.pump(w)
    scene = w._engine.edit_scene
    assert scene.find_entity(player_id).name == "Hero"
    key = (0, "x")
    inspector._component_vars[key].set("12.5")
    inspector._component_handler(0, "transform", "x", inspector._component_vars[key])()
    frontend.pump(w)
    assert scene.find_entity(player_id).get_component(TransformComponent).x == 12.5
    inspector._enabled_var.set(False)
    inspector._handle_toggle_enabled()
    frontend.pump(w)
    assert scene.find_entity(player_id).enabled is False
    w._act_undo()
    w._act_undo()
    w._act_undo()
    frontend.pump(w)
    entity = scene.find_entity(player_id)
    assert entity.name == "Player"
    assert entity.get_component(TransformComponent).x == 80.0
    assert entity.enabled is True


def test_play_pause_stop_cycles_restore_the_edit_scene(frontend, window) -> None:
    w = window()
    scene_id = w._engine.edit_scene.scene_id
    for _ in range(2):
        w._act_play()
        frontend.pump(w)
        assert w._engine.run_state == EngineRunState.PLAY
        assert w._actions.is_enabled("stop") is True
        assert w._actions.is_enabled("play") is False
        w._act_add_entity()  # blocked while playing
        assert len(w._engine.edit_scene.entities) == 2
        w._act_pause()
        assert w._engine.run_state == EngineRunState.PAUSED
        w._act_stop()
        frontend.pump(w)
        assert w._engine.run_state == EngineRunState.EDIT
        assert w._engine.edit_scene.scene_id == scene_id
        assert w._actions.is_enabled("play") is True
    console = frontend.console_text(w)
    assert console.count("[Engine] Play") == 2
    assert console.count("[Engine] Stopped — scene restored") == 2


def test_new_project_level_world_save_and_typed_labels(frontend, window, tmp_path) -> None:
    w = window()
    dialogs = frontend.dialogs(w)
    project = Project.create("Parity", tmp_path / "parity")
    w._project_workflow.open_loaded(project)
    frontend.pump(w)
    assert frontend.button_text(w, "save_document") == "Save Scene"

    with patch.object(dialogs, "ask_string", return_value="Forest"):
        w._act_new_level()
    frontend.pump(w)
    assert w._active_document.kind.value == "level"
    assert frontend.button_text(w, "save_document") == "Save Level"
    assert "LEVEL" in frontend.title(w)
    assert project.document_file("levels/Forest.level.pb").is_file()

    with patch.object(dialogs, "ask_string", return_value="Main World"):
        w._act_new_world()
    frontend.pump(w)
    assert w._active_document.kind.value == "world"
    assert frontend.button_text(w, "save_document") == "Save World"
    assert w._actions.is_enabled("add_entity") is False
    assert w._actions.is_enabled("add_world_level") is True
    assert project.document_file("worlds/Main World.world.pb").is_file()
    assert w._hierarchy._is_world is True
    assert [w._hierarchy._tree.item(i, "text") for i in w._hierarchy._row_state] == [
        "Main World",
        "Levels",
        "Connections",
    ]
