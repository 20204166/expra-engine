"""Real-project acceptance: The Second Mark through the Qt editor.

Runs a session against a *copy* of ``the-second-mark`` (the source project is never
modified): project open, chapter_one Level and the ``vey`` World (hierarchy, inspector,
viewport item structure, asset browser), an edit + save, Play/Stop, and Run Project.
"""

from __future__ import annotations

import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from tests.support.qt_app import wait_until
from tests.support.qt_editor import QtEditorHarness

SECOND_MARK = Path(
    os.environ.get(
        "EXPRA_SECOND_MARK_PROJECT",
        str(Path(__file__).parents[2] / "the-second-mark"),
    )
).expanduser()

pytestmark = [
    pytest.mark.skipif(
        not (SECOND_MARK / "project.json").is_file(), reason="The Second Mark is not checked out"
    ),
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]


def _copy_project(destination: Path) -> Path:
    shutil.copytree(
        SECOND_MARK,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "captures", ".git", "user_data"),
    )
    return destination


def _open_document(frontend: Any, window: Any, project: Project, relative: str) -> None:
    entry = AssetEntry(
        project.document_file(relative),
        Path(relative).name,
        False,
        ResourceId.from_project_path(relative, scheme="project"),
    )
    window._on_asset_open(entry)
    for _ in range(3):
        frontend.pump(window)


def _canvas_histogram(window: Any) -> dict[str, int]:
    canvas = window._viewport._canvas
    ids = canvas.find_all() if hasattr(canvas, "find_all") else canvas.find_withtag("all")
    # The grid is sized to the viewport, so it is excluded; everything drawn for the document counts.
    return dict(
        Counter(canvas.type(item) for item in ids if "grid" not in canvas.gettags(item))
    )


def _session(frontend: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    project_path = _copy_project(tmp_path / "qt-project")
    project = Project.load(project_path)
    window = frontend.make(Engine())
    result: dict[str, Any] = {}
    try:
        frontend.pump(window)
        window._project_workflow.open_loaded(project)
        frontend.pump(window)
        result["project_title"] = frontend.title(window)

        _open_document(frontend, window, project, "levels/chapter_one.level.pb")
        tree = window._hierarchy._tree
        rows = [tree.item(i, "text") for i in window._hierarchy._row_state]
        result["level_kind"] = window._active_document.kind.value
        result["level_rows"] = rows
        result["level_title"] = frontend.title(window)
        result["level_items"] = _canvas_histogram(window)
        result["asset_rows"] = sorted(
            window._assets._tree.item(i, "text") for i in window._assets._tree.get_children("")
        )

        player_id = next(i for i in window._hierarchy._row_state if "Courier" in tree.item(i, "text"))
        window._on_hierarchy_select((player_id,))
        frontend.pump(window)
        entity = window._engine.edit_scene.find_entity(player_id)
        result["selected_name"] = window._inspector._name_var.get()
        result["selected_fields"] = sorted(
            (index, field) for index, field in window._inspector._component_vars
        )
        transform = entity.get_component(TransformComponent)
        new_x = float(transform.x) + 3.0
        window._inspector._component_vars[(0, "x")].set(str(new_x))
        window._inspector._component_handler(
            0, "transform", "x", window._inspector._component_vars[(0, "x")]
        )()
        frontend.pump(window)
        result["edited_x"] = entity.get_component(TransformComponent).x
        result["dirty_after_edit"] = window._active_document.is_dirty
        window._act_save_document()
        frontend.pump(window)
        result["dirty_after_save"] = window._active_document.is_dirty
        result["saved_level_bytes"] = project.document_file(
            "levels/chapter_one.level.pb"
        ).read_bytes()

        _open_document(frontend, window, project, "worlds/vey.world.pb")
        world_tree = window._hierarchy._tree
        result["world_kind"] = window._active_document.kind.value
        result["world_rows"] = [
            world_tree.item(i, "text") for i in window._hierarchy._row_state
        ]
        window._on_hierarchy_select(("level:transit_district",))
        frontend.pump(window)
        result["world_inspector"] = window._inspector._world_inspection_values(
            window._active_document.document, "level:transit_district"
        )
        result["world_items"] = _canvas_histogram(window)

        _open_document(frontend, window, project, "levels/chapter_one.level.pb")
        window._act_play()
        wait_until(
            lambda: frontend.pump(window),
            lambda: window._engine.run_state is EngineRunState.PLAY,
            timeout=2.0,
        )
        result["play_state"] = window._engine.run_state.value
        window._act_stop()
        wait_until(
            lambda: frontend.pump(window),
            lambda: window._engine.run_state is EngineRunState.EDIT,
            timeout=2.0,
        )
        result["stop_state"] = window._engine.run_state.value
        result["edit_x_after_stop"] = (
            window._engine.edit_scene.find_entity(player_id).get_component(TransformComponent).x
        )

        window._project_workflow.run_project()
        controller = window._project_workflow._project_process_controller
        result["run_project_started"] = controller.process is not None
        wait_until(
            lambda: frontend.pump(window),
            lambda: controller.process is None or controller.process.poll() is not None,
            timeout=2.0,
        )
        window._act_stop()
        frontend.pump(window)
        result["run_project_stopped"] = controller.process is None
        result["final_state"] = window._engine.run_state.value
    finally:
        frontend.close(window)
    return result


def test_second_mark_editor_session(tmp_path, monkeypatch) -> None:
    result = _session(QtEditorHarness(tmp_path / "qt-prefs.json"), tmp_path, monkeypatch)

    assert result["level_kind"] == "level"
    assert len(result["level_rows"]) > 100
    assert result["world_kind"] == "world"
    assert result["world_rows"][0] == "The City of Vey"
    assert result["dirty_after_edit"] is True
    assert result["dirty_after_save"] is False
    saved = Project.load(tmp_path / "qt-project").load_scene("levels/chapter_one.level.pb")
    saved_courier = next(e for e in saved.entities if "Courier" in e.name)
    saved_transform = saved_courier.get_component(TransformComponent)
    assert saved_transform is not None
    assert saved_transform.x == result["edited_x"]
    assert result["play_state"] == EngineRunState.PLAY.value
    assert result["stop_state"] == EngineRunState.EDIT.value
    assert result["run_project_started"] is True
    assert result["run_project_stopped"] is True
    assert result["final_state"] == EngineRunState.EDIT.value
