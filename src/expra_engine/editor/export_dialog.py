"""Export dialog wired through ButtonCoordinator -> AppCoordinator -> TkDeliveryQueue.

Design:
  - ExportDialog owns only presentation and user input.
  - It dispatches "export_game" through ButtonCoordinator (no engine logic here).
  - AppCoordinator owns the background thread; TkDeliveryQueue owns UI-thread delivery.
  - GameExporter is pure; it never imports tkinter.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import ttkbootstrap as ttk

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.export.events import ExportProgressEvent
from expra_engine.export.exporter import GameExporter
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch

_ACTION_EXPORT = "export_game"
_ACTION_CANCEL = "export_game_cancel"


class ExportDialog(ttk.Toplevel):
    """Game export configuration and progress dialog."""

    def __init__(
        self,
        parent: tk.Misc,
        project_dir: Path,
        app_coordinator: AppCoordinator,
        button_coordinator: ButtonCoordinator,
        *,
        on_complete: Callable[[Path], None] | None = None,
        game_version: str = "1.0.0",
        entry_point: str = "__main__.py",
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.title("Export Game")
        self.resizable(False, False)
        self._project = project_dir
        self._app = app_coordinator
        self._buttons = button_coordinator
        self._on_complete = on_complete
        self._game_version = game_version
        self._entry_point = entry_point

        self._build_ui()
        self._register_actions()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 3}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Target:").grid(row=0, column=0, sticky="w", **pad)
        self._target_var = tk.StringVar(value="windows")
        ttk.Combobox(
            frame,
            textvariable=self._target_var,
            values=["windows", "linux"],
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(frame, text="Game Name:").grid(row=1, column=0, sticky="w", **pad)
        self._name_var = tk.StringVar(value=self._project.name)
        ttk.Entry(frame, textvariable=self._name_var, width=30).grid(
            row=1, column=1, sticky="ew", **pad
        )

        ttk.Label(frame, text="Version:").grid(row=2, column=0, sticky="w", **pad)
        self._version_var = tk.StringVar(value=self._game_version)
        ttk.Entry(frame, textvariable=self._version_var, width=14).grid(
            row=2, column=1, sticky="w", **pad
        )

        ttk.Label(frame, text="Python:").grid(row=3, column=0, sticky="w", **pad)
        self._python_var = tk.StringVar(value="3.12.4")
        ttk.Entry(frame, textvariable=self._python_var, width=14).grid(
            row=3, column=1, sticky="w", **pad
        )

        ttk.Label(frame, text="Output dir:").grid(row=4, column=0, sticky="w", **pad)
        self._output_var = tk.StringVar(value=str(self._project / "builds"))
        ttk.Entry(frame, textvariable=self._output_var, width=40).grid(
            row=4, column=1, sticky="ew", **pad
        )

        self._bytecode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Compile to bytecode (.pyc)",
            variable=self._bytecode_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

        # Progress log
        log_frame = ttk.LabelFrame(frame, text="Progress", padding=4)
        log_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=8)
        self._log = tk.Text(log_frame, height=8, width=64, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=7, column=0, columnspan=2, sticky="e")
        self._export_btn = ttk.Button(
            btn_frame,
            text="Export",
            command=self._buttons.command(_ACTION_EXPORT),
        )
        self._export_btn.pack(side="right", padx=(4, 0))
        ttk.Button(btn_frame, text="Close", command=self._on_close).pack(side="right")

        frame.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Action wiring
    # ------------------------------------------------------------------

    def _register_actions(self) -> None:
        self._buttons.register(_ACTION_EXPORT, self._start_export, replace=True)
        self._buttons.bind(self._export_btn, _ACTION_EXPORT)

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

    # ------------------------------------------------------------------
    # Callbacks (always called on the Tk thread via TkDeliveryQueue)
    # ------------------------------------------------------------------

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
        self.destroy()

    def _log_line(self, text: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")
