"""Own the lifecycle of a project process launched by the editor."""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import messagebox
from typing import Any

from expra_engine.core.project import Project
from expra_engine.messages import project as project_messages

_POLL_INTERVAL_MS = 100
_OUTPUT_TAIL_BYTES = 8192
_OUTPUT_MAX_CHARS = 2048


class ProjectProcessController:
    """Launch, monitor, report, and stop one child game process."""

    def __init__(self, window: Any) -> None:
        self._window = window
        self.process: subprocess.Popen[bytes] | None = None
        self.poll_id: str | None = None
        self._output_file: Any | None = None
        self._script_path: Path | None = None
        self._document_entrypoint: str | None = None

    def start(self, project: Project, script: Path) -> None:
        if not self.prepare_start():
            return
        output_file = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
        try:
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=project.path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=output_file,
            )
        except OSError as exc:
            output_file.close()
            self._window._console.log(
                project_messages.project_launch_failed(str(script), project.entrypoint, str(exc)),
                level="error",
            )
            messagebox.showerror("Run Project", str(exc), parent=self._window._root)
            return
        self.process = process
        self._output_file = output_file
        self._script_path = script
        self._document_entrypoint = project.entrypoint
        if not self._schedule_poll(process):
            try:
                self.stop()
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                detail = f"Could not monitor project process; stopping it also failed: {stop_error}"
            else:
                detail = "Could not monitor project process; it was stopped."
            messagebox.showerror("Run Project", detail, parent=self._window._root)
            return
        self._window._console.log(
            project_messages.project_started(
                project.script_entry_point,
                project.entrypoint,
            )
        )

    def prepare_start(self) -> bool:
        """Return whether a new launch may proceed, reaping an exited child."""
        process = self.process
        if process is None:
            return True
        try:
            return_code = process.poll()
        except OSError as exc:
            self._window._console.log(
                f"[Editor] Could not check project process: {exc}", level="error"
            )
            return False
        if return_code is None:
            return False
        self._report_exit(return_code)
        self._forget_process(process)
        self._close_output()
        return True

    def _schedule_poll(self, process: subprocess.Popen[bytes]) -> bool:
        if self.process is not process:
            return False
        timer = getattr(self._window, "_timer", None)
        if timer is None:
            return False
        try:
            identifier = timer.schedule(_POLL_INTERVAL_MS, self._poll, process)
        except Exception:  # noqa: BLE001
            return False
        if identifier is None:
            return False
        self.poll_id = identifier
        return True

    def _poll(self, process: subprocess.Popen[bytes]) -> None:
        if self.process is not process:
            return
        self.poll_id = None
        try:
            return_code = process.poll()
        except OSError as error:
            try:
                self.stop()
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                self._window._console.log(
                    f"[Editor] Could not poll project process ({error}) or stop it ({stop_error}).",
                    level="error",
                )
            else:
                self._window._console.log(
                    f"[Editor] Stopped project after process polling failed: {error}",
                    level="error",
                )
            return
        if return_code is not None:
            self._report_exit(return_code)
            self._forget_process(process)
            self._close_output()
            return
        if not self._schedule_poll(process):
            try:
                self.stop()
            except (OSError, subprocess.TimeoutExpired) as error:
                self._window._console.log(
                    f"[Editor] Could not monitor or stop project process: {error}",
                    level="error",
                )
            else:
                self._window._console.log(
                    "[Editor] Stopped project because process monitoring became unavailable.",
                    level="error",
                )

    def _report_exit(self, return_code: int) -> None:
        level = "info" if return_code == 0 else "error"
        detail = self._read_output_tail() if return_code != 0 else ""
        self._window._console.log(
            project_messages.project_exited(
                return_code,
                str(self._script_path or "(unknown)"),
                self._document_entrypoint,
                detail,
            ),
            level=level,
        )

    def _read_output_tail(self) -> str:
        output_file = self._output_file
        if output_file is None:
            return ""
        try:
            output_file.flush()
            output_file.seek(0, 2)
            size = output_file.tell()
            output_file.seek(max(0, size - _OUTPUT_TAIL_BYTES))
            data = output_file.read(_OUTPUT_TAIL_BYTES)
        except (OSError, ValueError):
            return ""
        text = data.decode("utf-8", errors="replace").strip()
        if len(text) > _OUTPUT_MAX_CHARS:
            text = text[-_OUTPUT_MAX_CHARS:]
        return text

    def _close_output(self) -> None:
        output_file = self._output_file
        self._output_file = None
        self._script_path = None
        self._document_entrypoint = None
        if output_file is not None:
            with contextlib.suppress(OSError):
                output_file.close()

    def _cancel_poll(self) -> None:
        identifier = self.poll_id
        self.poll_id = None
        timer = getattr(self._window, "_timer", None)
        if identifier is not None and timer is not None:
            timer.cancel(identifier)

    def _forget_process(self, process: subprocess.Popen[bytes]) -> None:
        if self.process is process:
            self.process = None
            self._cancel_poll()

    @staticmethod
    def _process_exited(process: subprocess.Popen[bytes]) -> bool:
        try:
            return process.poll() is not None
        except OSError:
            return False

    def stop(self) -> None:
        process = self.process
        self._cancel_poll()
        if process is None:
            self._close_output()
            return
        try:
            return_code = process.poll()
        except OSError:
            return_code = None
        if return_code is not None:
            self._report_exit(return_code)
            self._forget_process(process)
            self._close_output()
            return
        try:
            process.terminate()
        except OSError:
            if self._process_exited(process):
                self._forget_process(process)
                self._close_output()
                return
            self._schedule_poll(process)
            raise
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                if self._process_exited(process):
                    self._forget_process(process)
                    self._close_output()
                    return
                self._schedule_poll(process)
                raise
        except OSError:
            if self._process_exited(process):
                self._forget_process(process)
                self._close_output()
                return
            self._schedule_poll(process)
            raise
        self._forget_process(process)
        self._close_output()


__all__ = ["ProjectProcessController"]
