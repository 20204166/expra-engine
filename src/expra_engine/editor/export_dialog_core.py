"""Toolkit-independent Export dialog logic behind the Qt Export dialog.

Design:
  - The dialog owns only presentation and user input.
  - It dispatches "export_game" through ButtonCoordinator (no engine logic here).
  - AppCoordinator owns the background thread; the frontend's delivery queue
    owns UI-thread delivery.
  - GameExporter is pure; it never imports a GUI toolkit.

Frontends provide the form "variables" (``_target_var``, ``_name_var``,
``_version_var``, ``_python_var``, ``_output_var``, ``_bytecode_var`` -- anything
with ``get()``) and these hooks: ``_append_log``, ``_destroy_dialog`` and
``_export_button_widget``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.export.events import ExportProgressEvent
from expra_engine.export.exporter import GameExporter
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch, RuntimeProfile

_ACTION_EXPORT = "export_game"
_ACTION_CANCEL = "export_game_cancel"


class ExportDialogCore:
    _target_var: Any
    _name_var: Any
    _version_var: Any
    _python_var: Any
    _output_var: Any
    _bytecode_var: Any

    def _init_export_state(
        self,
        project_dir: Path,
        app_coordinator: AppCoordinator,
        button_coordinator: ButtonCoordinator,
        *,
        on_complete: Callable[[Path], None] | None,
        game_version: str,
        entry_point: str,
    ) -> None:
        self._project = project_dir
        self._app = app_coordinator
        self._buttons = button_coordinator
        self._on_complete = on_complete
        self._game_version = game_version
        self._entry_point = entry_point

    # -- frontend hooks -------------------------------------------------

    def _append_log(self, text: str) -> None:
        raise NotImplementedError

    def _destroy_dialog(self) -> None:
        raise NotImplementedError

    def _export_button_widget(self) -> Any:
        raise NotImplementedError

    # -- shared logic ---------------------------------------------

    def _register_actions(self) -> None:
        self._buttons.register(_ACTION_EXPORT, self._start_export, replace=True)
        self._buttons.bind(self._export_button_widget(), _ACTION_EXPORT)

    def _start_export(self) -> None:
        try:
            plan = ExportPlan(
                project_dir=self._project,
                entry_point=getattr(self, "_entry_point", "__main__.py"),
                output_dir=Path(self._output_var.get()).resolve(),
                target=ExportTarget(self._target_var.get()),
                game_name=self._name_var.get(),
                game_version=self._version_var.get(),
                python_version=self._python_var.get(),
                arch=PythonArch.AMD64,
                compile_bytecode=self._bytecode_var.get(),
                runtime_profile=RuntimeProfile.PYGAME,
            )
        except ValueError as e:
            self._log_line(f"Error: {e}")
            return

        def task(
            cancel: threading.Event,
            emit_progress: Callable[[str], None],
        ) -> Path:
            def on_event(event: ExportProgressEvent) -> None:
                emit_progress(f"[{event.phase.value:<22s}] {event.percent:3d}%  {event.message}")

            return GameExporter().export(plan, cancel=cancel, progress=on_event)

        self._log_line("Starting export…")
        self._app.run(
            _ACTION_EXPORT,
            task,
            on_result=self._on_result,
            on_error=self._on_error,
            on_progress=self._on_progress,
        )

    # -- callbacks (always called on the UI thread via the delivery queue) --

    def _on_result(self, _key: str, result: Path) -> None:
        self._log_line(f"Done: {result}")
        if self._on_complete is not None:
            self._on_complete(result)

    def _on_error(self, _key: str, error: str) -> None:
        self._log_line(f"Failed: {error}")

    def _on_progress(self, _key: str, message: str) -> None:
        self._log_line(message)

    def _on_close(self) -> None:
        self._app.cancel(_ACTION_EXPORT, "Cancelled by user")
        self._destroy_dialog()

    def _log_line(self, text: str) -> None:
        self._append_log(text)
