"""Menu/action state that must follow the editor's real state, in the Qt editor.

Two long-standing gaps fixed here:
  * the File > Open Recent menu was only built at startup, so it stayed "(none)" after opening
    a project until the next launch;
  * the Stop action stayed disabled while a Run Project child was running (the engine stays in
    edit state), so there was no in-editor way to end the game.
"""

from __future__ import annotations

import time

import pytest

from expra_engine.core.engine import EngineRunState
from expra_engine.core.project import Project
from tests.support.qt_app import wait_until

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _wait(frontend, w, condition, timeout: float = 10.0) -> bool:
    def _pump() -> None:
        frontend.pump(w)
        time.sleep(0.02)

    return wait_until(_pump, condition, timeout=timeout)


def test_open_recent_menu_lists_a_project_as_soon_as_it_is_opened(frontend, window, tmp_path) -> None:
    w = window()
    assert frontend.recent_labels(w) == ["(none)"]
    first = Project.create("First", tmp_path / "first")
    second = Project.create("Second", tmp_path / "second")

    w._project_workflow.open_loaded(first)
    frontend.pump(w)
    assert frontend.recent_labels(w) == [str(first.path)]

    w._project_workflow.open_loaded(second)
    frontend.pump(w)
    assert frontend.recent_labels(w) == [str(second.path), str(first.path)]

    w._project_workflow.open_loaded(first)  # re-opening moves it to the top, no duplicate
    frontend.pump(w)
    assert frontend.recent_labels(w) == [str(first.path), str(second.path)]


def test_stop_is_enabled_while_a_run_project_child_is_running(frontend, window, tmp_path) -> None:
    project = Project.create("Runner", tmp_path / "runner")
    (project.path / "__main__.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    w = window()
    w._project_workflow.open_loaded(project)
    frontend.pump(w)
    controller = w._project_workflow._project_process_controller
    assert w._actions.is_enabled("stop") is False

    w._project_workflow.run_project()
    frontend.pump(w)
    try:
        assert controller.process is not None and controller.process.poll() is None
        assert w._engine.run_state == EngineRunState.EDIT
        assert w._actions.is_enabled("stop") is True

        assert w._actions.dispatch("stop") is True  # what clicking the Stop button does
        frontend.pump(w)
        assert controller.process is None
        assert w._actions.is_enabled("stop") is False
        assert w._engine.run_state == EngineRunState.EDIT
    finally:
        controller.stop()


def test_stop_disables_again_when_the_child_exits_by_itself(frontend, window, tmp_path) -> None:
    project = Project.create("Quick", tmp_path / "quick")
    (project.path / "__main__.py").write_text("import time\ntime.sleep(0.6)\n", encoding="utf-8")
    w = window()
    w._project_workflow.open_loaded(project)
    frontend.pump(w)
    controller = w._project_workflow._project_process_controller

    w._project_workflow.run_project()
    frontend.pump(w)
    assert w._actions.is_enabled("stop") is True
    assert _wait(frontend, w, lambda: controller.process is None)
    assert w._actions.is_enabled("stop") is False
    assert "[Editor] Project exited" in frontend.console_text(w) or "exited" in frontend.console_text(w)


def test_stop_stays_disabled_when_nothing_is_running(frontend, window) -> None:
    w = window()
    assert w._actions.is_enabled("stop") is False
    w._act_play()
    frontend.pump(w)
    assert w._actions.is_enabled("stop") is True
    w._act_stop()
    frontend.pump(w)
    assert w._actions.is_enabled("stop") is False
