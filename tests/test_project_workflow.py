"""Headless real-project workflow coverage."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project, ProjectError
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.editor.script_tools import attach_script, create_behaviour_script
from expra_engine.runtime import ScriptComponent, ScriptRegistry
from expra_engine.runtime.input import PhysicalInput


class RecordingTimer:
    def __init__(self) -> None:
        self.callbacks: dict[str, tuple[Callable[..., None], tuple[object, ...]]] = {}
        self.history: dict[str, tuple[Callable[..., None], tuple[object, ...]]] = {}
        self.cancelled: list[str] = []
        self._next_identifier = 0
        self.fail_schedule = False

    def schedule(self, _delay: int, callback: Callable[..., None], *args: object) -> str | None:
        if self.fail_schedule:
            return None
        self._next_identifier += 1
        identifier = f"timer-{self._next_identifier}"
        self.callbacks[identifier] = (callback, args)
        self.history[identifier] = (callback, args)
        return identifier

    def cancel(self, identifier: str | None) -> bool:
        if identifier is None:
            return True
        self.cancelled.append(identifier)
        self.callbacks.pop(identifier, None)
        return True

    def fire_next(self) -> None:
        identifier = next(iter(self.callbacks))
        callback, args = self.callbacks.pop(identifier)
        callback(*args)

    def fire_even_if_cancelled(self, identifier: str) -> None:
        callback, args = self.history[identifier]
        self.callbacks.pop(identifier, None)
        callback(*args)


class TestProjectWorkflow(unittest.TestCase):
    def test_run_project_launches_the_project_script_as_a_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            engine = SimpleNamespace(project=project)
            window = SimpleNamespace(
                _engine=engine,
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with patch("expra_engine.editor.project_workflow.subprocess.Popen") as launch:
                workflow.run_project()

            launch.assert_called_once_with(
                [sys.executable, str(project.path / "__main__.py")],
                cwd=project.path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertIs(workflow._project_process, launch.return_value)

    def test_double_run_keeps_one_live_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            process = MagicMock()
            process.poll.return_value = None
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with patch(
                "expra_engine.editor.project_workflow.subprocess.Popen", return_value=process
            ) as launch:
                workflow.run_project()
                workflow.run_project()

            launch.assert_called_once()
            self.assertIs(workflow._project_process, process)

    def test_invalid_script_path_outside_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Runtime", root / "runtime")
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            project.script_entry_point = "../outside.py"
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch("expra_engine.editor.project_workflow.subprocess.Popen") as launch,
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.run_project()

            launch.assert_not_called()
            error.assert_called_once()
            self.assertIsNone(workflow._project_process)

    def test_script_symlink_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Runtime", root / "runtime")
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            link = project.path / "linked.py"
            link.symlink_to(outside)
            project.script_entry_point = "linked.py"
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch("expra_engine.editor.project_workflow.subprocess.Popen") as launch,
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.run_project()

            launch.assert_not_called()
            error.assert_called_once()
            self.assertIsNone(workflow._project_process)

    def test_child_that_exits_early_is_reaped_and_reported_by_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            (project.path / "__main__.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            workflow.run_project()
            process = workflow._project_process
            self.assertIsNotNone(process)
            assert process is not None
            self.assertTrue(timer.callbacks)
            self.assertEqual(process.wait(timeout=5), 7)

            timer.fire_next()

            self.assertIsNone(workflow._project_process)
            window._console.log.assert_called()
            self.assertIn("7", window._console.log.call_args.args[0])

    def test_poll_failure_stops_child_instead_of_repeating_poll_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            process = MagicMock()
            process.poll.side_effect = [OSError("poll failed"), None]
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)
            with patch(
                "expra_engine.editor.project_workflow.subprocess.Popen", return_value=process
            ):
                workflow.run_project()

            timer.fire_next()

            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=2)
            self.assertIsNone(workflow._project_process)
            self.assertFalse(timer.callbacks)

    def test_monitor_schedule_failure_stops_the_new_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            process = MagicMock()
            process.poll.return_value = None
            timer = RecordingTimer()
            timer.fail_schedule = True
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            with (
                patch(
                    "expra_engine.editor.project_workflow.subprocess.Popen",
                    return_value=process,
                ),
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.run_project()

            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=2)
            self.assertIsNone(workflow._project_process)
            error.assert_called_once()

    def test_failed_candidate_load_keeps_current_child_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Project.create("Current", Path(tmp) / "current")
            process = MagicMock()
            process.poll.return_value = None
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=current),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=timer,
                _observer=None,
            )
            workflow = ProjectWorkflow(window)
            with patch(
                "expra_engine.editor.project_workflow.subprocess.Popen", return_value=process
            ):
                workflow.run_project()

            failed_project = MagicMock()
            failed_project.load_document.side_effect = ProjectError("broken document")
            with self.assertRaisesRegex(ProjectError, "broken document"):
                workflow.open_loaded(failed_project)

            self.assertIs(window._engine.project, current)
            self.assertIs(workflow._project_process, process)
            process.terminate.assert_not_called()

    def test_kill_timeout_keeps_process_handle_for_retry(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired("game", 2),
            subprocess.TimeoutExpired("game", 2),
        ]
        workflow._project_process = process
        stop_error: Exception | None = None
        try:
            workflow.stop_project()
        except Exception as error:  # noqa: BLE001
            stop_error = error

        self.assertIsInstance(stop_error, subprocess.TimeoutExpired)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertIs(workflow._project_process, process)

    def test_save_as_outside_project_preserves_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Workflow", root / "project")
            previous_target = project.document_file()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project, edit_scene=project.load_scene()),
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch(
                    "expra_engine.editor.project_workflow.filedialog.asksaveasfilename",
                    return_value=str(root / "outside.scene.pb"),
                ),
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.save_scene_as()

            self.assertEqual(window._last_save_path, previous_target)
            error.assert_called_once()

    def test_save_as_write_failure_preserves_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Workflow", Path(tmp) / "project")
            previous_target = project.document_file()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project, edit_scene=project.load_scene()),
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch(
                    "expra_engine.editor.project_workflow.filedialog.asksaveasfilename",
                    return_value=str(project.scenes_dir / "copy.scene.pb"),
                ),
                patch.object(project, "save_document", side_effect=OSError("disk full")),
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.save_scene_as()

            self.assertEqual(window._last_save_path, previous_target)
            error.assert_called_once()

    def test_launch_failure_keeps_editor_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            scene = project.load_scene()
            previous_target = project.document_file()
            engine = SimpleNamespace(project=project, edit_scene=scene)
            window = SimpleNamespace(
                _engine=engine,
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch(
                    "expra_engine.editor.project_workflow.subprocess.Popen",
                    side_effect=OSError("process limit reached"),
                ),
                patch("expra_engine.editor.project_workflow.messagebox.showerror") as error,
            ):
                workflow.run_project()

            self.assertIs(engine.project, project)
            self.assertIs(engine.edit_scene, scene)
            self.assertEqual(window._last_save_path, previous_target)
            self.assertIsNone(workflow._project_process)
            error.assert_called_once()

    def test_stop_project_terminates_a_running_child_process(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        workflow._project_process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)
        self.assertIsNone(workflow._project_process)

    def test_stop_project_kills_a_child_that_does_not_terminate(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("game", 2), None]
        workflow._project_process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertIsNone(workflow._project_process)

    def test_failed_terminate_keeps_the_handle_and_reschedules_poll(self) -> None:
        timer = RecordingTimer()
        window = SimpleNamespace(_engine=SimpleNamespace(project=None), _timer=timer)
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.terminate.side_effect = PermissionError("terminate denied")
        workflow._project_process = process

        with self.assertRaisesRegex(PermissionError, "terminate denied"):
            workflow.stop_project()

        self.assertIs(workflow._project_process, process)
        self.assertTrue(timer.callbacks)

    def test_terminate_race_with_exit_is_treated_as_stopped(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        process.terminate.side_effect = ProcessLookupError("child already exited")
        workflow._project_process = process

        workflow.stop_project()

        self.assertIsNone(workflow._project_process)
        process.terminate.assert_called_once_with()

    def test_late_poll_from_replaced_process_cannot_clear_new_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            first = MagicMock()
            first.poll.return_value = None
            first.wait.return_value = 0
            second = MagicMock()
            second.poll.return_value = None
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            with patch(
                "expra_engine.editor.project_workflow.subprocess.Popen",
                side_effect=(first, second),
            ):
                workflow.run_project()
                first_poll = workflow._project_poll_id
                assert first_poll is not None
                workflow.stop_project()
                workflow.run_project()

            self.assertIs(workflow._project_process, second)
            timer.fire_even_if_cancelled(first_poll)
            self.assertIs(workflow._project_process, second)
            second.poll.assert_not_called()

    def test_new_project_has_standard_runtime_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            entry_point = project.path / "__main__.py"
            self.assertTrue(entry_point.is_file())
            self.assertIn("run_project", entry_point.read_text(encoding="utf-8"))

    def test_create_script_attach_save_close_reopen_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Workflow", Path(tmp) / "workflow")
            scene = project.load_scene()
            entity = scene.create_entity("Player")
            entity.add_component(TransformComponent())
            script_id = create_behaviour_script(
                project.path, "scripts/player.py", "PlayerBehaviour"
            )
            attach_script(entity, script_id, "PlayerBehaviour")
            project.save_scene(scene)

            reopened = Project.load(project.path)
            loaded_scene = reopened.load_scene()
            loaded_entity = loaded_scene.find_entity(entity.entity_id)
            assert loaded_entity is not None
            component = loaded_entity.components[-1]
            assert isinstance(component, ScriptComponent)
            self.assertEqual(str(component.script_id), "project://scripts/player.py")
            self.assertIsNotNone(
                ScriptRegistry(reopened.path).resolve(component.script_id, "PlayerBehaviour")
            )

    def test_project_relocation_keeps_logical_script_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a" / "game"
            project = Project.create("Game", source)
            create_behaviour_script(project.path, "scripts/player.py", "PlayerBehaviour")
            relocated = Path(tmp) / "b" / "game"
            relocated.parent.mkdir()
            source.rename(relocated)
            reopened = Project.load(relocated)
            self.assertIsNotNone(
                ScriptRegistry(reopened.path).resolve(
                    "project://scripts/player.py", "PlayerBehaviour"
                )
            )

    def test_imports_audio_as_a_project_asset_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Audio Game", root / "game")
            source = root / "theme.ogg"
            source.write_bytes(b"fake audio")
            resource = project.import_asset(source, "audio/theme.ogg")
            self.assertEqual(str(resource), "assets://audio/theme.ogg")
            self.assertEqual((project.assets_dir / "audio/theme.ogg").read_bytes(), b"fake audio")
            with self.assertRaises(ValueError):
                project.import_asset(source, "audio/theme.ogg")

    def test_concurrent_asset_imports_do_not_overwrite_the_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Audio Game", root / "game")
            first_source = root / "first.ogg"
            second_source = root / "second.ogg"
            first_source.write_bytes(b"first")
            second_source.write_bytes(b"second")
            destination = (project.assets_dir / "audio/theme.ogg").resolve()
            barrier = threading.Barrier(2)
            path_exists = Path.exists

            def wait_after_absent_check(path: Path) -> bool:
                exists = path_exists(path)
                if path == destination and not exists:
                    barrier.wait()
                return exists

            def import_asset(source: Path) -> tuple[Path, bool]:
                try:
                    project.import_asset(source, "audio/theme.ogg")
                except ProjectError:
                    return source, False
                return source, True

            with patch.object(Path, "exists", wait_after_absent_check), ThreadPoolExecutor(
                max_workers=2
            ) as executor:
                results = list(executor.map(import_asset, (first_source, second_source)))

            winners = [source for source, succeeded in results if succeeded]
            self.assertEqual(len(winners), 1)
            self.assertEqual(destination.read_bytes(), winners[0].read_bytes())

    def test_input_settings_are_project_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Input Game", Path(tmp) / "game")
            project.set_input_binding("move_left", "keyboard:left")
            project.save()
            reopened = Project.load(project.path)
            self.assertEqual(reopened.input_settings, {"move_left": "keyboard:left"})
            engine = Engine()
            engine.set_project(reopened)
            self.assertEqual(len(engine.input_map.press(PhysicalInput("keyboard", "left"))), 1)


if __name__ == "__main__":
    unittest.main()
