"""The Qt Export dialog runs the shared export flow and reports it in its log."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from expra_engine.core.project import Project
from expra_engine.export.events import ExportPhase, ExportProgressEvent

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


_PLANS: list = []


class _FakeExporter:
    def export(self, plan, *, cancel: threading.Event, progress) -> Path:
        _PLANS.append(plan)
        progress(ExportProgressEvent(ExportPhase.PLANNING, "planning build", 5))
        progress(ExportProgressEvent(ExportPhase.PROMOTING, "promoting build", 95))
        return plan.output_dir / "build"


def _make_dialog(w, project):
    from expra_engine.editor.qt.export_dialog import ExportDialog

    dialog = ExportDialog(
        w, project.path, w._coordinator, w._actions, game_version=project.game_version
    )
    dialog.show()
    return dialog


def test_export_flow_and_log(frontend, window, tmp_path) -> None:
    _PLANS.clear()
    project = Project.create("ExportFlow", tmp_path / "project")
    w = window()
    w._project_workflow.open_loaded(project)
    frontend.pump(w)
    dialog = _make_dialog(w, project)
    frontend.pump(w)
    try:
        dialog._output_var.set(str(tmp_path / "out"))
        dialog._target_var.set("linux")
        dialog._name_var.set("Parity Game")
        with patch("expra_engine.editor.export_dialog_core.GameExporter", _FakeExporter):
            assert w._actions.dispatch("export_game") is True
            deadline = time.monotonic() + 10
            while "Done:" not in dialog.log_text() and time.monotonic() < deadline:
                frontend.pump(w)
                time.sleep(0.02)
        lines = [line for line in dialog.log_text().splitlines() if line.strip()]
        assert lines[0] == "Starting export…"
        assert lines[1].endswith("5%  planning build")
        assert lines[2].endswith("95%  promoting build")
        assert lines[3] == f"Done: {tmp_path / 'out' / 'build'}"
        plan = _PLANS[0]
        assert plan.game_name == "Parity Game"
        assert plan.target.value == "linux"
        assert plan.compile_bytecode is True
        assert plan.runtime_profile.value == "pygame"
    finally:
        dialog._on_close()
        frontend.pump(w)


def test_invalid_form_logs_error_without_starting(frontend, window, tmp_path) -> None:
    _PLANS.clear()
    project = Project.create("ExportInvalid", tmp_path / "project")
    w = window()
    w._project_workflow.open_loaded(project)
    dialog = _make_dialog(w, project)
    frontend.pump(w)
    try:
        dialog._name_var.set("")
        with patch("expra_engine.editor.export_dialog_core.GameExporter", _FakeExporter):
            w._actions.dispatch("export_game")
            frontend.pump(w)
        assert dialog.log_text().strip().startswith("Error:")
        assert _PLANS == []
    finally:
        dialog._on_close()
        frontend.pump(w)
