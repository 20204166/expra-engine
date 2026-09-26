"""Tests for Phase F multi-level workflow: Open/Save As/Duplicate Scene, Run Project.

Also regression-covers the ``_act_save_scene_silent`` fix: saving must always
route through ``Project.save_document`` (which omits resolve-from-source scene-
instance content), never a raw ``scene.to_dict()`` write.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.core.scene.document_codec import decode_protobuf
from expra_engine.ui.editor_window import EditorWindow
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()


def _make_project(root: Path) -> Project:
    project = Project.create("Test Project", root / "Test Project")
    second = Scene("Level Two")
    second.create_entity("Marker")
    project.save_document(second, "scenes/level_two.scene.pb")
    project.save()
    return project


def _make_room_segment(root: Path) -> None:
    """A tiny reusable scene under scenes/ for instance-leak regression tests."""
    room = Scene("Room Segment")
    room.create_entity("Door")
    project = Project.load(root)
    project.save_document(room, "scenes/room_segment.scene.pb")


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class MultiLevelWorkflowTests(unittest.TestCase):
    def _window_with_project(self, root: Path) -> tuple[EditorWindow, Project]:
        project = _make_project(root)
        window = EditorWindow(Engine())
        window._project_workflow.open_loaded(project)
        window._root.update()
        return window, project

    def test_open_scene_switches_edit_scene_and_last_save_path(self) -> None:
        with TemporaryDirectory() as directory:
            window, project = self._window_with_project(Path(directory))
            try:
                self.assertEqual(window._engine.edit_scene.name, "Main")  # type: ignore[union-attr]
                window._project_workflow.open_scene("scenes/level_two.scene.pb")
                window._root.update()
                self.assertEqual(window._engine.edit_scene.name, "Level Two")  # type: ignore[union-attr]
                self.assertEqual(
                    window._last_save_path, project.document_file("scenes/level_two.scene.pb")
                )
            finally:
                window._on_close()

    def test_open_scene_guard_declines_and_keeps_original_scene(self) -> None:
        with TemporaryDirectory() as directory:
            window, _project = self._window_with_project(Path(directory))
            try:
                window._act_add_entity()  # dirties the command stack
                window._root.update()
                self.assertTrue(window._command_stack.can_undo)
                with patch(
                    "expra_engine.editor.project_workflow.messagebox.askyesnocancel",
                    return_value=None,  # Cancel
                ):
                    window._project_workflow.open_scene("scenes/level_two.scene.pb")
                self.assertEqual(window._engine.edit_scene.name, "Main")  # type: ignore[union-attr]
            finally:
                window._on_close()

    def test_save_as_writes_new_path_registers_it_and_becomes_the_new_save_target(self) -> None:
        with TemporaryDirectory() as directory:
            window, project = self._window_with_project(Path(directory))
            try:
                new_path = project.scenes_dir / "branched.scene.pb"
                with patch(
                    "expra_engine.editor.project_workflow.filedialog.asksaveasfilename",
                    return_value=str(new_path),
                ):
                    window._project_workflow.save_scene_as()
                self.assertTrue(new_path.is_file())
                self.assertIn("scenes/branched.scene.pb", project.scene_paths())
                self.assertEqual(window._last_save_path, new_path)

                window._act_add_entity()
                window._root.update()
                window._act_save_scene()
                saved = decode_protobuf(new_path.read_bytes())
                self.assertEqual(len(saved["entities"]), len(window._engine.edit_scene.entities))  # type: ignore[union-attr]
                original = decode_protobuf(project.document_file().read_bytes())
                self.assertNotEqual(len(original["entities"]), len(saved["entities"]))
            finally:
                window._on_close()

    def test_save_does_not_leak_resolved_scene_instance_content(self) -> None:
        """Regression test for the _act_save_scene_silent bug: it used to
        bypass Project.save_scene and write scene.to_dict()'s default
        (include_instance_content=True), persisting resolve-from-source
        content straight into the file.
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = _make_project(root)
            _make_room_segment(project.path)
            window = EditorWindow(Engine())
            window._project_workflow.open_loaded(project)
            window._root.update()
            try:
                scene = window._engine.edit_scene
                instance_root = scene.create_entity("Room Instance")  # type: ignore[union-attr]
                instance_root.add_component(TransformComponent(x=3.0, y=4.0))
                instance_root.add_component(SceneInstanceComponent("scenes/room_segment.scene.pb"))
                from expra_engine.core.scene import resolve_scene_instances

                resolve_scene_instances(
                    scene,  # type: ignore[arg-type]
                    resolve_source=lambda path: project.load_scene(path),
                )
                self.assertGreater(len(scene.entities), 1)  # type: ignore[union-attr]

                window._last_save_path = project.scene_file()
                window._act_save_scene_silent()

                saved = decode_protobuf(project.document_file().read_bytes())
                saved_ids = {entity["entity_id"] for entity in saved["entities"]}
                self.assertIn(instance_root.entity_id, saved_ids)
                materialized_ids = {
                    entity.entity_id
                    for entity in scene.entities  # type: ignore[union-attr]
                    if scene.is_instance_materialized(entity.entity_id)  # type: ignore[union-attr]
                }
                self.assertTrue(materialized_ids)
                self.assertFalse(materialized_ids & saved_ids)
            finally:
                window._on_close()

    def test_autosave_path_also_does_not_leak_instance_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = _make_project(root)
            _make_room_segment(project.path)
            window = EditorWindow(Engine())
            window._project_workflow.open_loaded(project)
            window._root.update()
            try:
                scene = window._engine.edit_scene
                instance_root = scene.create_entity("Room Instance")  # type: ignore[union-attr]
                instance_root.add_component(SceneInstanceComponent("scenes/room_segment.scene.pb"))
                from expra_engine.core.scene import resolve_scene_instances

                resolve_scene_instances(
                    scene,
                    resolve_source=lambda path: project.load_scene(path),  # type: ignore[arg-type]
                )
                window._last_save_path = project.scene_file()

                window._start_autosave()
                window._root.after_cancel(window._autosave_after_id)  # don't actually reschedule
                window._act_save_scene_silent()

                saved = decode_protobuf(project.document_file().read_bytes())
                saved_ids = {entity["entity_id"] for entity in saved["entities"]}
                self.assertIn(instance_root.entity_id, saved_ids)
                self.assertEqual(len(saved["entities"]), 1)  # only the instance root, no children
            finally:
                window._on_close()

    def test_duplicate_scene_gets_fresh_scene_id_and_switches_editor(self) -> None:
        with TemporaryDirectory() as directory:
            window, project = self._window_with_project(Path(directory))
            try:
                original_scene_id = window._engine.edit_scene.scene_id  # type: ignore[union-attr]
                window._project_workflow.duplicate_scene("main_copy")
                window._root.update()
                self.assertEqual(window._engine.edit_scene.name, "main_copy")  # type: ignore[union-attr]
                self.assertNotEqual(window._engine.edit_scene.scene_id, original_scene_id)  # type: ignore[union-attr]
                self.assertIn("scenes/main_copy.scene.pb", project.scene_paths())
                self.assertTrue((project.scenes_dir / "main_copy.scene.pb").is_file())
            finally:
                window._on_close()

    def test_duplicate_scene_refuses_to_overwrite_existing_path(self) -> None:
        with TemporaryDirectory() as directory:
            window, _project = self._window_with_project(Path(directory))
            try:
                with patch(
                    "expra_engine.editor.project_workflow.messagebox.showerror"
                ) as mock_error:
                    window._project_workflow.duplicate_scene("level_two")
                mock_error.assert_called_once()
                self.assertEqual(window._engine.edit_scene.name, "Main")  # type: ignore[union-attr]
            finally:
                window._on_close()

    def test_run_project_from_a_non_start_scene_preserves_edit_scene_on_stop(self) -> None:
        with TemporaryDirectory() as directory:
            window, project = self._window_with_project(Path(directory))
            try:
                window._project_workflow.open_scene("scenes/level_two.scene.pb")
                window._root.update()
                window._act_add_entity()  # unsaved edit on Level Two
                window._root.update()
                entity_count_before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]

                window._project_workflow.run_project()
                window._root.update()
                self.assertIsNotNone(window._project_workflow._project_process)
                self.assertEqual(window._engine.run_state, EngineRunState.EDIT)
                self.assertEqual(window._engine.edit_scene.name, "Level Two")  # type: ignore[union-attr]

                window._act_stop()
                window._root.update()
                self.assertEqual(window._engine.run_state, EngineRunState.EDIT)
                self.assertEqual(window._engine.edit_scene.name, "Level Two")  # type: ignore[union-attr]
                self.assertEqual(
                    len(window._engine.edit_scene.entities),
                    entity_count_before,  # type: ignore[union-attr]
                )
                self.assertEqual(
                    window._last_save_path, project.document_file("scenes/level_two.scene.pb")
                )
            finally:
                window._on_close()

    def test_run_project_when_already_on_start_scene_starts_a_child_process(self) -> None:
        with TemporaryDirectory() as directory:
            window, _project = self._window_with_project(Path(directory))
            try:
                before_scene_id = window._engine.edit_scene.scene_id  # type: ignore[union-attr]
                window._project_workflow.run_project()
                window._root.update()
                self.assertIsNotNone(window._project_workflow._project_process)
                self.assertEqual(window._engine.run_state, EngineRunState.EDIT)
                window._act_stop()
                window._root.update()
                self.assertIsNone(window._project_workflow._project_process)
                self.assertEqual(window._engine.edit_scene.scene_id, before_scene_id)  # type: ignore[union-attr]
            finally:
                window._on_close()


if __name__ == "__main__":
    unittest.main()
