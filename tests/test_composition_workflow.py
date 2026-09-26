"""Real-Tk tests for Phase E composition workflow: asset/scene-instance drop
onto the viewport, and hierarchy drag-reparent.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.editor.assets import AssetEntry
from expra_engine.editor.commands import drop_asset_on_viewport, reparent_selection_to
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.visual_components import SpriteComponent
from expra_engine.ui.editor_window import EditorWindow
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()


def _make_project_with_room(tmp: str) -> Project:
    project = Project.create("Composition", Path(tmp) / "proj")
    room = Scene("Room Segment", scene_id="room-segment")
    room.create_entity("Wall").add_component(TransformComponent(x=1.0))
    project.save_scene(room, "scenes/room_segment.json")
    (project.assets_dir / "hero.png").write_bytes(b"not a real png, just a placeholder")
    return project


def _entry_for(project: Project, relative: str) -> AssetEntry:
    path = project.path / relative
    return AssetEntry(
        path, path.name, False, ResourceId.from_project_path(relative, scheme="project")
    )


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class AssetAndSceneInstanceDropTests(unittest.TestCase):
    def test_image_drop_creates_positioned_sprite_entity_undoably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project_with_room(tmp)
            window = EditorWindow(Engine())
            try:
                window._project_workflow.open_loaded(project)
                window._root.update()
                scene = window._engine.edit_scene
                before = len(scene.entities)
                history_before = len(window._command_stack.history)

                canvas = window._viewport._canvas
                x_root = canvas.winfo_rootx() + canvas.winfo_width() // 2
                y_root = canvas.winfo_rooty() + canvas.winfo_height() // 2
                entry = _entry_for(project, "assets/hero.png")

                drop_asset_on_viewport(window, entry, x_root, y_root)
                window._root.update()

                self.assertEqual(len(scene.entities), before + 1)
                self.assertEqual(len(window._command_stack.history), history_before + 1)
                new_entity = next(e for e in scene.entities if e.name == "hero")
                sprite = new_entity.get_component(SpriteComponent)
                self.assertIsNotNone(sprite)
                assert sprite is not None
                self.assertIn("hero.png", sprite.asset)
                self.assertEqual(window._selected_ids, (new_entity.entity_id,))

                window._act_undo()
                self.assertEqual(len(scene.entities), before)
            finally:
                window._on_close()

    def test_scene_instance_drop_materializes_children_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project_with_room(tmp)
            window = EditorWindow(Engine())
            try:
                window._project_workflow.open_loaded(project)
                window._root.update()
                scene = window._engine.edit_scene

                canvas = window._viewport._canvas
                x_root = canvas.winfo_rootx() + canvas.winfo_width() // 2
                y_root = canvas.winfo_rooty() + canvas.winfo_height() // 2
                entry = _entry_for(project, "scenes/room_segment.json")

                drop_asset_on_viewport(window, entry, x_root, y_root)
                window._root.update()

                names = {e.name for e in scene.entities}
                self.assertIn("room_segment", names)
                self.assertIn("Wall", names)  # materialized live, no save/reopen needed
                root_entity = next(e for e in scene.entities if e.name == "room_segment")
                self.assertIsNotNone(root_entity.get_component(SceneInstanceComponent))

                window._act_undo()
                self.assertNotIn("Wall", {e.name for e in scene.entities})
            finally:
                window._on_close()

    def test_dropping_a_scene_onto_itself_is_rejected_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project_with_room(tmp)
            window = EditorWindow(Engine())
            try:
                window._project_workflow.open_loaded(project)  # opens scenes/main.scene.pb
                window._root.update()
                scene = window._engine.edit_scene
                before = len(scene.entities)

                canvas = window._viewport._canvas
                x_root = canvas.winfo_rootx() + canvas.winfo_width() // 2
                y_root = canvas.winfo_rooty() + canvas.winfo_height() // 2
                entry = _entry_for(project, "scenes/main.scene.pb")

                drop_asset_on_viewport(window, entry, x_root, y_root)
                window._root.update()

                self.assertEqual(len(scene.entities), before)  # no phantom entity
            finally:
                window._on_close()

    def test_plain_click_in_asset_browser_still_selects_without_dragging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project_with_room(tmp)
            window = EditorWindow(Engine())
            try:
                window._project_workflow.open_loaded(project)
                window._root.update()
                entry = _entry_for(project, "assets/hero.png")
                window._assets._current_directory = project.assets_dir
                window._assets.render_entries([entry])
                window._root.update()
                iid = window._assets._iid_for_path(entry.path)
                bbox = window._assets._tree.bbox(iid)
                self.assertIsNotNone(bbox)
                assert bbox is not None
                x, y = bbox[0] + 2, bbox[1] + 2
                tree = window._assets._tree
                tree.focus_force()
                tree.event_generate("<ButtonPress-1>", x=x, y=y, when="now")
                tree.event_generate("<ButtonRelease-1>", x=x, y=y, when="now")
                window._root.update()

                self.assertIsNotNone(window._assets.selected_entry)
            finally:
                window._on_close()


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class HierarchyDragReparentTests(unittest.TestCase):
    def _add_entities(self, window: EditorWindow, count: int) -> list[str]:
        ids = []
        for _ in range(count):
            window._act_add_entity()
            window._root.update()
            ids.append(window._selected_ids[0])
        return ids

    def test_single_entity_reparent_is_undoable(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            scene = window._engine.edit_scene
            child = scene.find_entity(ids[0])
            self.assertIsNone(child.parent_id)

            reparent_selection_to(window, (ids[0],), ids[1])
            self.assertEqual(child.parent_id, ids[1])

            window._act_undo()
            self.assertIsNone(child.parent_id)
        finally:
            window._on_close()

    def test_multi_selection_reparent_is_one_undo_step(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 3)
            scene = window._engine.edit_scene
            history_before = len(window._command_stack.history)

            reparent_selection_to(window, (ids[0], ids[1]), ids[2])

            self.assertEqual(scene.find_entity(ids[0]).parent_id, ids[2])
            self.assertEqual(scene.find_entity(ids[1]).parent_id, ids[2])
            self.assertEqual(len(window._command_stack.history), history_before + 1)

            window._act_undo()
            self.assertIsNone(scene.find_entity(ids[0]).parent_id)
            self.assertIsNone(scene.find_entity(ids[1]).parent_id)
        finally:
            window._on_close()

    def test_reparent_onto_own_descendant_is_rejected_without_crashing(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            scene = window._engine.edit_scene
            reparent_selection_to(window, (ids[1],), ids[0])  # ids[1] is now a child of ids[0]
            self.assertEqual(scene.find_entity(ids[1]).parent_id, ids[0])

            # Now try to make the parent a child of its own child -- must be
            # rejected (cycle), not crash, and not corrupt the hierarchy.
            reparent_selection_to(window, (ids[0],), ids[1])

            self.assertIsNone(scene.find_entity(ids[0]).parent_id)
        finally:
            window._on_close()

    def test_dropping_onto_empty_space_reparents_to_root(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            scene = window._engine.edit_scene
            reparent_selection_to(window, (ids[0],), ids[1])
            self.assertEqual(scene.find_entity(ids[0]).parent_id, ids[1])

            reparent_selection_to(window, (ids[0],), None)
            self.assertIsNone(scene.find_entity(ids[0]).parent_id)
        finally:
            window._on_close()

    def test_drag_reparent_via_real_tk_dispatch(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            scene = window._engine.edit_scene
            tree = window._hierarchy._tree
            window._root.update()
            child_bbox = tree.bbox(ids[0])
            parent_bbox = tree.bbox(ids[1])
            self.assertIsNotNone(child_bbox)
            self.assertIsNotNone(parent_bbox)
            assert child_bbox is not None and parent_bbox is not None

            tree.focus_force()
            tree.event_generate(
                "<ButtonPress-1>", x=child_bbox[0] + 2, y=child_bbox[1] + 2, when="now"
            )
            tree.event_generate(
                "<ButtonRelease-1>", x=parent_bbox[0] + 2, y=parent_bbox[1] + 2, when="now"
            )
            window._root.update()

            self.assertEqual(scene.find_entity(ids[0]).parent_id, ids[1])
        finally:
            window._on_close()

    def test_plain_click_in_hierarchy_still_selects_without_dragging(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 1)
            tree = window._hierarchy._tree
            window._root.update()
            bbox = tree.bbox(ids[0])
            self.assertIsNotNone(bbox)
            assert bbox is not None
            x, y = bbox[0] + 2, bbox[1] + 2
            tree.focus_force()
            tree.event_generate("<ButtonPress-1>", x=x, y=y, when="now")
            tree.event_generate("<ButtonRelease-1>", x=x, y=y, when="now")
            window._root.update()

            self.assertEqual(window._selected_ids, (ids[0],))
        finally:
            window._on_close()


if __name__ == "__main__":
    unittest.main()
