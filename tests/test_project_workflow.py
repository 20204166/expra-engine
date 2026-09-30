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
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World, WorldConnection
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.contributions import EditorContext
from expra_engine.editor.preferences import EditorPreferences
from expra_engine.editor.project_process import ProjectProcessController
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
    def test_open_loaded_world_uses_typed_active_document_and_world_play_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            world = World(
                "Main World",
                world_id="main-world",
                levels=(LevelDescriptor("town", "levels/town.level.pb"),),
                initial_level_id="town",
            )
            project.save_document(world, "worlds/main.world.pb")
            project.set_entrypoint("worlds/main.world.pb")
            engine = Engine()
            active_document = ActiveDocument()
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _observer=None,
                _runtime_preview=MagicMock(),
                _viewport=MagicMock(),
                _editor_context=EditorContext(
                    engine=engine,
                    actions=MagicMock(),
                    ui=MagicMock(),
                    project=None,
                ),
                _assets=MagicMock(),
                _preferences=EditorPreferences(),
                _selected_ids=(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _console=MagicMock(),
                _update_project_actions=MagicMock(),
                _present_all=MagicMock(),
            )

            ProjectWorkflow(window).open_loaded(project)

            self.assertEqual(active_document.document, world)
            self.assertEqual(active_document.kind.value, "world")
            self.assertEqual(active_document.path, project.document_file("worlds/main.world.pb"))
            self.assertIs(active_document.play_source, active_document.document)
            self.assertEqual(engine.world_streaming_system.world, world)
            self.assertIsNone(engine.edit_scene)
            engine.world_streaming_system.close()

    def test_saving_world_marks_active_document_clean_only_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            world = World(
                "Main World",
                world_id="main-world",
                levels=(LevelDescriptor("town", "levels/town.level.pb"),),
                initial_level_id="town",
            )
            path = "worlds/main.world.pb"
            project.save_document(world, path)
            document = project.load_world(path)
            active_document = ActiveDocument()
            active_document.open(document, project.document_file(path))
            active_document.mark_dirty()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project, edit_scene=None),
                _active_document=active_document,
                _last_save_path=project.document_file(path),
                _console=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            with (
                patch.object(project, "save_document", side_effect=OSError("disk full")),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                workflow.save_scene_silent()
            self.assertTrue(active_document.is_dirty)

            workflow.save_scene_silent()

            self.assertFalse(active_document.is_dirty)
            self.assertEqual(project.load_world(path), document)

    def test_duplicate_world_preserves_level_references_without_copying_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            world = World(
                "Main World",
                world_id="main-world",
                levels=(LevelDescriptor("town", "levels/town.level.pb"),),
                initial_level_id="town",
            )
            project.save_document(world, "worlds/main.world.pb")
            active_document = ActiveDocument()
            active_document.open(world, project.document_file("worlds/main.world.pb"))
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _last_save_path=active_document.path,
                _selected_ids=(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _console=MagicMock(),
                _present_all=MagicMock(),
            )

            ProjectWorkflow(window).duplicate_scene("copy")

            duplicate = project.load_world("worlds/copy.world.pb")
            self.assertNotEqual(duplicate.world_id, world.world_id)
            self.assertEqual(duplicate.levels, world.levels)
            self.assertFalse(project.document_file("levels/town.level.pb").exists())
            self.assertEqual(active_document.document, duplicate)
            self.assertEqual(active_document.path, project.document_file("worlds/copy.world.pb"))
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_open_document_switches_from_level_to_world_without_scene_aliasing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            level = project.load_scene("scenes/main.scene.pb")
            world = World(
                "Main World",
                world_id="main-world",
                levels=(LevelDescriptor("town", "levels/town.level.pb"),),
                initial_level_id="town",
            )
            project.save_document(world, "worlds/main.world.pb")
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(level)
            active_document = ActiveDocument()
            active_document.open(level, project.document_file("scenes/main.scene.pb"))
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _observer=None,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _console=MagicMock(),
                _present_all=MagicMock(),
            )

            ProjectWorkflow(window).open_document("worlds/main.world.pb")

            self.assertEqual(active_document.kind.value, "world")
            self.assertEqual(active_document.document, world)
            self.assertIsNone(engine.edit_scene)
            assert engine.world_streaming_system is not None
            self.assertEqual(engine.world_streaming_system.world, world)
            engine.world_streaming_system.close()

    def test_new_world_saves_typed_empty_document_and_opens_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            engine = Engine()
            engine.set_project(project)
            active_document = ActiveDocument()
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=None,
                _selected_ids=(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _console=MagicMock(),
                _present_all=MagicMock(),
            )

            ProjectWorkflow(window).new_world("Open World")

            restored = project.load_world("worlds/Open World.world.pb")
            self.assertEqual(restored.name, "Open World")
            self.assertEqual(active_document.kind.value, "world")
            self.assertEqual(active_document.document, restored)
            self.assertEqual(project.world_paths(), ("worlds/Open World.world.pb",))
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_new_level_saves_typed_document_and_opens_it_for_authoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Level", Path(tmp) / "level")
            engine = Engine()
            engine.set_project(project)
            active_document = ActiveDocument()
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=None,
                _selected_ids=(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _console=MagicMock(),
                _present_all=MagicMock(),
            )

            ProjectWorkflow(window).new_level("Forest")

            saved = project.load_document("levels/Forest.level.pb")
            self.assertIsInstance(saved, Level)
            self.assertEqual(active_document.kind.value, "level")
            self.assertEqual(active_document.document.name, saved.name)
            self.assertEqual(active_document.path, project.document_file("levels/Forest.level.pb"))
            self.assertIs(engine.edit_scene, active_document.document)

    def test_add_level_to_world_adds_reference_without_copying_document_and_is_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            source = LevelDescriptor("source", "levels/source.level.pb")
            project.save_document(Level("Source"), source.resource_path)
            world = World("Main", world_id="main")
            active_document = ActiveDocument()
            active_document.open(world, project.document_file("worlds/main.world.pb"))
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _observer=None,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _present_all=MagicMock(),
                _update_undo_redo_state=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            workflow.add_level_to_world(source.resource_path, origin=(20.0, 30.0))

            self.assertEqual(len(active_document.document.levels), 1)
            descriptor = active_document.document.levels[0]
            self.assertEqual(descriptor.resource_path, source.resource_path)
            self.assertEqual(descriptor.origin, (20.0, 30.0))
            self.assertEqual(active_document.document.initial_level_id, descriptor.instance_id)
            self.assertTrue(active_document.is_dirty)
            self.assertEqual(project.load_document(source.resource_path).name, "Source")
            self.assertTrue(active_document.command_stack.undo())
            self.assertEqual(active_document.document.levels, ())
            self.assertTrue(project.document_file(source.resource_path).exists())
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_level_placement_edit_moves_bounds_and_is_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            world = World(
                "Main",
                world_id="main",
                levels=(
                    LevelDescriptor(
                        "town",
                        "levels/town.level.pb",
                        origin=(1.0, 2.0),
                        bounds=(0.0, 0.0, 100.0, 50.0),
                    ),
                ),
                initial_level_id="town",
            )
            active_document = ActiveDocument()
            active_document.open(world, project.document_file("worlds/main.world.pb"))
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _update_undo_redo_state=MagicMock(),
                _present_all=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            workflow.update_level_placement("town", (20.0, 30.0))

            placed = active_document.document.levels[0]
            self.assertEqual(placed.origin, (20.0, 30.0))
            self.assertEqual(placed.bounds, (19.0, 28.0, 100.0, 50.0))
            self.assertTrue(active_document.is_dirty)
            active_document.command_stack.undo()
            self.assertEqual(active_document.document.levels[0].origin, (1.0, 2.0))
            self.assertEqual(active_document.document.levels[0].bounds, (0.0, 0.0, 100.0, 50.0))
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_create_seamless_connection_validates_named_anchors_and_world_adjacency(self) -> None:
        from expra_engine.runtime.level_anchor import LevelAnchorComponent

        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            town = Level("Town")
            exit_entity = town.create_entity("East Gate")
            exit_entity.add_component(TransformComponent(x=100.0))
            exit_entity.add_component(LevelAnchorComponent("east", kind="exit"))
            forest = Level("Forest")
            entry = forest.create_entity("West Entry")
            entry.add_component(LevelAnchorComponent("west", kind="entrance"))
            project.save_document(town, "levels/town.level.pb")
            project.save_document(forest, "levels/forest.level.pb")
            world = World(
                "Main",
                world_id="main",
                levels=(
                    LevelDescriptor("town", "levels/town.level.pb"),
                    LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
                ),
                initial_level_id="town",
            )
            active_document = ActiveDocument()
            active_document.open(world, project.document_file("worlds/main.world.pb"))
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _observer=None,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _update_undo_redo_state=MagicMock(),
                _present_all=MagicMock(),
            )
            workflow = ProjectWorkflow(window)
            connection = WorldConnection("town-forest", "town", "east", "forest", "west")

            workflow.add_world_connection(connection)

            self.assertEqual(active_document.document.connections, (connection,))
            self.assertTrue(active_document.is_dirty)
            active_document.command_stack.undo()
            self.assertEqual(active_document.document.connections, ())
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_remove_connection_then_level_preserves_world_graph_validation_and_undo(self) -> None:
        world = World(
            "Main",
            world_id="main",
            levels=(
                LevelDescriptor("town", "levels/town.level.pb"),
                LevelDescriptor("forest", "levels/forest.level.pb"),
            ),
            connections=(WorldConnection("gate", "town", "east", "forest", "west"),),
            initial_level_id="town",
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            project.save_document(world, "worlds/main.world.pb")
            active_document = ActiveDocument()
            active_document.open(world, project.document_file("worlds/main.world.pb"))
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=active_document.path,
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _update_undo_redo_state=MagicMock(),
                _present_all=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            with self.assertRaisesRegex(ProjectError, "connections"):
                workflow.remove_level_from_world("town")
            workflow.remove_world_connection("gate")
            workflow.remove_level_from_world("town")

            self.assertEqual(tuple(item.instance_id for item in active_document.document.levels), ("forest",))
            self.assertEqual(active_document.document.initial_level_id, "forest")
            active_document.command_stack.undo()
            self.assertEqual(len(active_document.document.connections), 0)
            active_document.command_stack.undo()
            self.assertEqual(active_document.document, world)
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_set_initial_level_is_undoable_and_clears_unrelated_entrance(self) -> None:
        world = World(
            "Main",
            world_id="main",
            levels=(
                LevelDescriptor("town", "levels/town.level.pb"),
                LevelDescriptor("forest", "levels/forest.level.pb"),
            ),
            initial_level_id="town",
            initial_entrance_id="town_gate",
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("World", Path(tmp) / "world")
            active_document = ActiveDocument()
            active_document.open(world)
            engine = Engine()
            engine.set_project(project)
            engine.set_scene(None)
            window = SimpleNamespace(
                _engine=engine,
                _active_document=active_document,
                _command_stack=active_document.command_stack,
                _last_save_path=None,
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _update_undo_redo_state=MagicMock(),
                _present_all=MagicMock(),
            )
            workflow = ProjectWorkflow(window)

            workflow.set_initial_level("forest")

            self.assertEqual(active_document.document.initial_level_id, "forest")
            self.assertIsNone(active_document.document.initial_entrance_id)
            active_document.command_stack.undo()
            self.assertEqual(active_document.document, world)
            assert engine.world_streaming_system is not None
            engine.world_streaming_system.close()

    def test_run_project_launches_the_project_script_as_a_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            engine = SimpleNamespace(project=project)
            window = SimpleNamespace(
                _engine=engine,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)
            self.assertIsInstance(workflow._project_process_controller, ProjectProcessController)

            with patch("expra_engine.editor.project_process.subprocess.Popen") as launch:
                workflow.run_project()

            launch.assert_called_once()
            args, kwargs = launch.call_args
            self.assertEqual(args[0], [sys.executable, str(project.path / "__main__.py")])
            self.assertEqual(kwargs["cwd"], project.path)
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
            self.assertIs(kwargs["stderr"], workflow._project_process_controller._output_file)
            self.assertIs(workflow._project_process_controller.process, launch.return_value)
            workflow._project_process_controller._close_output()

    def test_double_run_keeps_one_live_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            process = MagicMock()
            process.poll.return_value = None
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)

            with patch(
                "expra_engine.editor.project_process.subprocess.Popen", return_value=process
            ) as launch:
                workflow.run_project()
                workflow.run_project()

            launch.assert_called_once()
            self.assertIs(workflow._project_process_controller.process, process)

    def test_live_project_process_short_circuits_before_entrypoint_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            process = MagicMock()
            process.poll.return_value = None
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window)
            workflow._project_process_controller.process = process

            with patch.object(
                workflow, "_script_entry_point_path", side_effect=AssertionError("validated")
            ):
                workflow.run_project()

            process.poll.assert_called_once_with()

    def test_invalid_script_path_outside_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Runtime", root / "runtime")
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            project.script_entry_point = "../outside.py"
            dialogs = MagicMock()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)

            with patch("expra_engine.editor.project_process.subprocess.Popen") as launch:
                workflow.run_project()

            launch.assert_not_called()
            dialogs.show_error.assert_called_once()
            self.assertIsNone(workflow._project_process_controller.process)

    def test_script_symlink_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Runtime", root / "runtime")
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            link = project.path / "linked.py"
            link.symlink_to(outside)
            project.script_entry_point = "linked.py"
            dialogs = MagicMock()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
            )
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)

            with patch("expra_engine.editor.project_process.subprocess.Popen") as launch:
                workflow.run_project()

            launch.assert_not_called()
            dialogs.show_error.assert_called_once()
            self.assertIsNone(workflow._project_process_controller.process)

    def test_child_that_exits_early_is_reaped_and_reported_by_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            (project.path / "__main__.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            workflow.run_project()
            process = workflow._project_process_controller.process
            self.assertIsNotNone(process)
            assert process is not None
            self.assertTrue(timer.callbacks)
            self.assertEqual(process.wait(timeout=5), 7)

            timer.fire_next()

            self.assertIsNone(workflow._project_process_controller.process)
            window._console.log.assert_called()
            self.assertIn("7", window._console.log.call_args.args[0])

    def test_child_failure_reports_bounded_stderr_and_both_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            level = Level("Start")
            project.save_document(level, "levels/start.level.pb")
            project.set_entrypoint("levels/start.level.pb")
            project.save()
            script = project.path / "__main__.py"
            script.write_text(
                "import sys\n"
                "sys.stderr.write('diagnostic-noise-' * 1000 + '\\n')\n"
                "print('useful startup failure', file=sys.stderr, flush=True)\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            timer = RecordingTimer()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            workflow.run_project()
            process = workflow._project_process_controller.process
            output_file = workflow._project_process_controller._output_file
            self.assertIsNotNone(process)
            self.assertIsNotNone(output_file)
            assert process is not None
            assert output_file is not None
            self.assertEqual(process.wait(timeout=5), 7)
            timer.fire_next()

            messages = [call.args[0] for call in window._console.log.call_args_list]
            failure = next(message for message in messages if "exited with status 7" in message)
            self.assertIn("useful startup failure", failure)
            self.assertIn("\nuseful startup failure", failure)
            self.assertIn("__main__.py", failure)
            self.assertIn("levels/start.level.pb", failure)
            self.assertLessEqual(len(failure), 2400)
            self.assertTrue(output_file.closed)

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
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)
            with patch(
                "expra_engine.editor.project_process.subprocess.Popen", return_value=process
            ):
                workflow.run_project()

            timer.fire_next()

            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=2)
            self.assertIsNone(workflow._project_process_controller.process)
            self.assertFalse(timer.callbacks)

    def test_monitor_schedule_failure_stops_the_new_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            (project.path / "__main__.py").write_text("pass\n", encoding="utf-8")
            process = MagicMock()
            process.poll.return_value = None
            timer = RecordingTimer()
            timer.fail_schedule = True
            dialogs = MagicMock()
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project),
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
                _dialogs=dialogs,
            )
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)

            with patch(
                "expra_engine.editor.project_process.subprocess.Popen",
                return_value=process,
            ):
                workflow.run_project()

            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=2)
            self.assertIsNone(workflow._project_process_controller.process)
            dialogs.show_error.assert_called_once()

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
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
                _observer=None,
            )
            workflow = ProjectWorkflow(window)
            with patch(
                "expra_engine.editor.project_process.subprocess.Popen", return_value=process
            ):
                workflow.run_project()

            failed_project = MagicMock()
            failed_project.load_document.side_effect = ProjectError("broken document")
            with self.assertRaisesRegex(ProjectError, "broken document"):
                workflow.open_loaded(failed_project)

            self.assertIs(window._engine.project, current)
            self.assertIs(workflow._project_process_controller.process, process)
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
        workflow._project_process_controller.process = process
        stop_error: Exception | None = None
        try:
            workflow.stop_project()
        except Exception as error:  # noqa: BLE001
            stop_error = error

        self.assertIsInstance(stop_error, subprocess.TimeoutExpired)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertIs(workflow._project_process_controller.process, process)

    def test_save_as_outside_project_preserves_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Project.create("Workflow", root / "project")
            previous_target = project.document_file()
            active_document = ActiveDocument()
            active_document.open(project.load_scene(), previous_target)
            dialogs = MagicMock()
            dialogs.ask_save_file.return_value = str(root / "outside.scene.pb")
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project, edit_scene=project.load_scene()),
                _active_document=active_document,
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
            )
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)
            workflow.save_scene_as()

            self.assertEqual(window._last_save_path, previous_target)
            dialogs.show_error.assert_called_once()

    def test_save_as_write_failure_preserves_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Workflow", Path(tmp) / "project")
            previous_target = project.document_file()
            active_document = ActiveDocument()
            active_document.open(project.load_scene(), previous_target)
            window = SimpleNamespace(
                _engine=SimpleNamespace(project=project, edit_scene=project.load_scene()),
                _active_document=active_document,
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
            )
            dialogs = MagicMock()
            dialogs.ask_save_file.return_value = str(project.scenes_dir / "copy.scene.pb")
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)

            with patch.object(project, "save_document", side_effect=OSError("disk full")):
                workflow.save_scene_as()

            self.assertEqual(window._last_save_path, previous_target)
            dialogs.show_error.assert_called_once()

    def test_launch_failure_keeps_editor_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project.create("Runtime", Path(tmp) / "runtime")
            scene = project.load_scene()
            previous_target = project.document_file()
            engine = SimpleNamespace(project=project, edit_scene=scene)
            dialogs = MagicMock()
            window = SimpleNamespace(
                _engine=engine,
                _last_save_path=previous_target,
                _console=MagicMock(),
                _root=MagicMock(),
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=RecordingTimer(),
                _dialogs=dialogs,
            )
            workflow = ProjectWorkflow(window, dialog_provider=dialogs)

            with patch(
                "expra_engine.editor.project_process.subprocess.Popen",
                side_effect=OSError("process limit reached"),
            ):
                workflow.run_project()

            self.assertIs(engine.project, project)
            self.assertIs(engine.edit_scene, scene)
            self.assertEqual(window._last_save_path, previous_target)
            self.assertIsNone(workflow._project_process_controller.process)
            dialogs.show_error.assert_called_once()

    def test_stop_project_terminates_a_running_child_process(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        workflow._project_process_controller.process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)
        self.assertIsNone(workflow._project_process_controller.process)

    def test_stop_project_kills_a_child_that_does_not_terminate(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("game", 2), None]
        workflow._project_process_controller.process = process

        workflow.stop_project()

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertIsNone(workflow._project_process_controller.process)

    def test_failed_terminate_keeps_the_handle_and_reschedules_poll(self) -> None:
        timer = RecordingTimer()
        window = SimpleNamespace(_engine=SimpleNamespace(project=None), _timer=timer)
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.return_value = None
        process.terminate.side_effect = PermissionError("terminate denied")
        workflow._project_process_controller.process = process

        with self.assertRaisesRegex(PermissionError, "terminate denied"):
            workflow.stop_project()

        self.assertIs(workflow._project_process_controller.process, process)
        self.assertTrue(timer.callbacks)

    def test_terminate_race_with_exit_is_treated_as_stopped(self) -> None:
        window = SimpleNamespace(_engine=SimpleNamespace(project=None))
        workflow = ProjectWorkflow(window)
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        process.terminate.side_effect = ProcessLookupError("child already exited")
        workflow._project_process_controller.process = process

        workflow.stop_project()

        self.assertIsNone(workflow._project_process_controller.process)
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
                _set_window_title=MagicMock(),
                _populate_recent_projects=MagicMock(),
                _timer=timer,
            )
            workflow = ProjectWorkflow(window)

            with patch(
                "expra_engine.editor.project_process.subprocess.Popen",
                side_effect=(first, second),
            ):
                workflow.run_project()
                first_poll = workflow._project_process_controller.poll_id
                assert first_poll is not None
                workflow.stop_project()
                workflow.run_project()

            self.assertIs(workflow._project_process_controller.process, second)
            timer.fire_even_if_cancelled(first_poll)
            self.assertIs(workflow._project_process_controller.process, second)
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
