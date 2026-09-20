"""Tk-free wiring tests for :mod:`expra_engine.editor.export_dialog`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from expra_engine.editor.export_dialog import _ACTION_EXPORT, ExportDialog
from expra_engine.export.plan import RuntimeProfile


class ExportDialogActionTests(unittest.TestCase):
    """Exercise ExportDialog callbacks without opening a real Tk window."""

    def _make_dialog(self, tmp_path: Path) -> tuple[ExportDialog, MagicMock, MagicMock]:
        app = MagicMock()
        buttons = MagicMock()
        dialog = object.__new__(ExportDialog)
        dialog._project = tmp_path
        dialog._app = app
        dialog._buttons = buttons
        dialog._on_complete = None
        dialog._log = MagicMock()
        dialog._target_var = MagicMock(get=lambda: "linux")
        dialog._name_var = MagicMock(get=lambda: "mygame")
        dialog._version_var = MagicMock(get=lambda: "1.0.0")
        dialog._python_var = MagicMock(get=lambda: "3.12.4")
        dialog._output_var = MagicMock(get=lambda: str(tmp_path / "builds"))
        dialog._bytecode_var = MagicMock(get=lambda: False)
        return dialog, app, buttons

    def test_register_actions_registers_and_binds_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dialog, _, buttons = self._make_dialog(Path(tmp))
            dialog._export_btn = MagicMock()

            dialog._register_actions()

            buttons.register.assert_called_once_with(
                _ACTION_EXPORT, dialog._start_export, replace=True
            )
            buttons.bind.assert_called_once_with(dialog._export_btn, _ACTION_EXPORT)

    def test_start_export_dispatches_valid_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "__main__.py").write_text("print('hello')\n", encoding="utf-8")
            dialog, app, _ = self._make_dialog(project)

            dialog._start_export()

            app.run.assert_called_once()
            self.assertEqual(app.run.call_args.args[0], _ACTION_EXPORT)
            self.assertTrue(callable(app.run.call_args.args[1]))
            self.assertEqual(app.run.call_args.kwargs["on_result"], dialog._on_result)

    def test_start_export_uses_pygame_runtime_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            project = Path(tmp)
            (project / "__main__.py").write_text("print('hello')\n", encoding="utf-8")
            dialog, _, _ = self._make_dialog(project)
            with patch("expra_engine.editor.export_dialog.ExportPlan") as plan:
                dialog._start_export()
            self.assertEqual(plan.call_args.kwargs["runtime_profile"], RuntimeProfile.PYGAME)

    def test_result_logs_and_calls_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dialog, _, _ = self._make_dialog(Path(tmp))
            received: list[Path] = []
            dialog._on_complete = received.append
            result = Path(tmp) / "build"

            dialog._on_result("export_game", result)

            self.assertEqual(received, [result])
            dialog._log.insert.assert_called_once_with("end", f"Done: {result}\n")

    def test_close_cancels_export_and_destroys_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dialog, app, _ = self._make_dialog(Path(tmp))
            dialog.destroy = MagicMock()

            dialog._on_close()

            app.cancel.assert_called_once_with(_ACTION_EXPORT, "Cancelled by user")
            dialog.destroy.assert_called_once_with()

    def test_log_line_appends_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dialog, _, _ = self._make_dialog(Path(tmp))

            dialog._log_line("hello")

            dialog._log.config.assert_any_call(state="normal")
            dialog._log.insert.assert_called_once_with("end", "hello\n")
            dialog._log.config.assert_any_call(state="disabled")

    def test_invalid_plan_logs_error_without_dispatching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dialog, app, _ = self._make_dialog(Path(tmp))
            dialog._name_var = MagicMock(get=lambda: "")

            dialog._start_export()

            app.run.assert_not_called()
            dialog._log.insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
