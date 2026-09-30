"""Qt Export dialog -- same form, progress log and actions as ``editor.export_dialog``.

The plan building, background export, progress delivery and cancel logic is the
shared ``ExportDialogCore``; this module only builds the Qt form.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.editor.export_dialog_core import _ACTION_EXPORT, ExportDialogCore
from expra_engine.editor.qt.action_widget import QtActionWidget
from expra_engine.editor.qt.field_vars import BooleanVar, ComboVar, StringVar


class ExportDialog(ExportDialogCore, QDialog):
    """Game export configuration and progress dialog."""

    def __init__(
        self,
        parent: Any,
        project_dir: Path,
        app_coordinator: AppCoordinator,
        button_coordinator: ButtonCoordinator,
        *,
        on_complete: Callable[[Path], None] | None = None,
        game_version: str = "1.0.0",
        entry_point: str = "__main__.py",
    ) -> None:
        QDialog.__init__(self, parent)
        self.setWindowTitle("Export Game")
        self._init_export_state(
            project_dir,
            app_coordinator,
            button_coordinator,
            on_complete=on_complete,
            game_version=game_version,
            entry_point=entry_point,
        )
        self._build_ui()
        self._register_actions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        target = QComboBox()
        target.addItems(["windows", "linux"])
        name = QLineEdit(self._project.name)
        version = QLineEdit(self._game_version)
        python = QLineEdit("3.12.4")
        output = QLineEdit(str(self._project / "builds"))
        bytecode = QCheckBox("Compile to bytecode (.pyc)")
        bytecode.setChecked(True)
        form.addRow("Target:", target)
        form.addRow("Game Name:", name)
        form.addRow("Version:", version)
        form.addRow("Python:", python)
        form.addRow("Output dir:", output)
        form.addRow(bytecode)
        layout.addLayout(form)
        self._target_var = ComboVar(target)
        self._name_var = StringVar(name)
        self._version_var = StringVar(version)
        self._python_var = StringVar(python)
        self._output_var = StringVar(output)
        self._bytecode_var = BooleanVar(bytecode)

        progress = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        progress_layout.addWidget(self._log)
        layout.addWidget(progress)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._export_btn = QPushButton("Export")
        close = QPushButton("Close")
        close.clicked.connect(lambda *_a: self._on_close())
        buttons.addWidget(close)
        buttons.addWidget(self._export_btn)
        layout.addLayout(buttons)

    def _export_button_widget(self) -> QtActionWidget:
        return QtActionWidget(self._export_btn)

    def _destroy_dialog(self) -> None:
        self.close()
        self.deleteLater()

    def _append_log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def log_text(self) -> str:
        return str(self._log.toPlainText())

    def closeEvent(self, event: Any) -> None:
        self._app.cancel(_ACTION_EXPORT, "Cancelled by user")
        event.accept()


__all__ = ["ExportDialog"]
