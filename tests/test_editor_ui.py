"""Real-widget regression tests for the mature editor shell."""

import tkinter as tk
import unittest
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.core.component_schema import PropertyDescriptor
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.editor.assets import AssetEntry
from expra_engine.editor.runtime_preview import RuntimePreviewLoop
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.visual_components import TextComponent
from expra_engine.ui.asset_browser import AssetBrowserPanel
from expra_engine.ui.editor_window import EditorWindow
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel
from expra_engine.ui.styles import COLORS, configure_app_styles, editor_entity_kind
from expra_engine.ui.viewport import ViewportPanel
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()


class RuntimePreviewLoopTests(unittest.TestCase):
    def test_stop_clears_timer_when_root_is_already_destroyed(self) -> None:
        class DeadRoot:
            def after_cancel(self, _identifier: str) -> None:
                raise RuntimeError("event loop is stopping")

        loop = RuntimePreviewLoop(
            DeadRoot(),
            cast(Any, SimpleNamespace(run_state=EngineRunState.EDIT)),
            lambda: None,
        )
        loop._after_id = "timer"

        loop.stop()

        self.assertIsNone(loop._after_id)

    def test_start_ignores_destroyed_root(self) -> None:
        class DeadRoot:
            def after(self, _delay: int, _callback: object) -> str:
                raise tk.TclError("event loop is stopping")

            def winfo_exists(self) -> bool:
                return False

        loop = RuntimePreviewLoop(
            DeadRoot(),
            cast(Any, SimpleNamespace(run_state=EngineRunState.EDIT)),
            lambda: None,
        )

        loop.start()

        self.assertIsNone(loop._after_id)

    def test_start_does_not_schedule_when_root_reports_destroyed(self) -> None:
        class DeadRoot:
            def after(self, _delay: int, _callback: object) -> str:
                return "unexpected-timer"

            def winfo_exists(self) -> bool:
                return False

        loop = RuntimePreviewLoop(
            DeadRoot(),
            cast(Any, SimpleNamespace(run_state=EngineRunState.PLAY)),
            lambda: None,
        )

        loop.start()

        self.assertIsNone(loop._after_id)

    def test_tick_stops_rescheduling_when_root_is_destroyed(self) -> None:
        class DeadRoot:
            def after(self, _delay: int, _callback: object) -> str:
                raise RuntimeError("event loop is stopping")

            def winfo_exists(self) -> bool:
                return False

        engine = cast(Any, SimpleNamespace(run_state=EngineRunState.PLAY, tick=lambda: None))
        rendered: list[str] = []
        loop = RuntimePreviewLoop(DeadRoot(), engine, lambda: rendered.append("rendered"))

        loop._tick()

        self.assertEqual(rendered, [])
        self.assertIsNone(loop._after_id)

    def test_start_preserves_live_root_scheduling_errors(self) -> None:
        class BrokenRoot:
            def after(self, _delay: int, _callback: object) -> str:
                raise tk.TclError("event loop is unavailable")

            def winfo_exists(self) -> bool:
                return True

        loop = RuntimePreviewLoop(
            BrokenRoot(),
            cast(Any, SimpleNamespace(run_state=EngineRunState.PLAY)),
            lambda: None,
        )

        with self.assertRaises(tk.TclError):
            loop.start()

    def test_tick_does_not_update_engine_when_root_reports_destroyed(self) -> None:
        class DeadRoot:
            def after(self, _delay: int, _callback: object) -> str:
                return "unexpected-timer"

            def winfo_exists(self) -> bool:
                return False

        ticks: list[str] = []
        engine = cast(
            Any,
            SimpleNamespace(run_state=EngineRunState.PLAY, tick=lambda: ticks.append("tick")),
        )
        rendered: list[str] = []
        loop = RuntimePreviewLoop(DeadRoot(), engine, lambda: rendered.append("rendered"))

        loop._tick()

        self.assertEqual(ticks, [])
        self.assertEqual(rendered, [])
        self.assertIsNone(loop._after_id)


def test_inspector_value_conversion_uses_descriptor_rejection_policy() -> None:
    descriptor = PropertyDescriptor("x", "X", float, 0.0, minimum=-10.0, maximum=10.0)
    assert InspectorPanel.convert_component_value(descriptor, "2.5", 1.0) == 2.5
    assert InspectorPanel.convert_component_value(descriptor, "bad", 1.0) == 1.0


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class EditorPanelTests(unittest.TestCase):
    def test_editor_entity_marker_roles_are_name_based(self) -> None:
        self.assertEqual(editor_entity_kind("Camera"), "camera")
        self.assertEqual(editor_entity_kind("Camera Marker"), "camera_compact")
        self.assertEqual(editor_entity_kind("Player"), "player")
        self.assertEqual(editor_entity_kind("Player Marker"), "player_compact")
        self.assertIsNone(editor_entity_kind("Enemy"))

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root_path = Path.cwd() / "assets"
        self.root.geometry("1100x700")
        self.root.update_idletasks()

    def tearDown(self) -> None:
        with suppress(tk.TclError):
            self.root.destroy()

    def test_hierarchy_preserves_parent_nesting(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Nested")
        parent = scene.create_entity("Parent")
        child = scene.create_entity("Child", parent_id=parent.entity_id)

        panel.render(scene)
        self.root.update_idletasks()

        self.assertEqual(panel._tree.get_children(""), (parent.entity_id,))
        self.assertEqual(panel._tree.get_children(parent.entity_id), (child.entity_id,))

    def test_asset_browser_renders_logical_ids_and_display_names(self) -> None:
        panel = AssetBrowserPanel(self.root, root_directory=self.root_path)
        panel.pack(fill="both", expand=True)
        folder = AssetEntry(
            self.root_path / "textures",
            "textures",
            True,
            ResourceId.parse("assets://textures"),
        )
        entry = AssetEntry(
            self.root_path / "textures" / "hero.png",
            "hero.png",
            False,
            ResourceId.parse("assets://textures/hero.png"),
        )

        panel.render_entries((folder, entry))

        row = panel._tree.get_children("")[0]
        child = panel._tree.get_children(row)[0]
        self.assertEqual(panel._tree.item(row, "text"), "textures")
        self.assertEqual(panel._tree.item(child, "text"), "hero.png")
        self.assertEqual(panel._tree.set(child, "logical_id"), "assets://textures/hero.png")

    def test_hierarchy_render_retains_existing_items_and_selection(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Retained")
        entity = scene.create_entity("Player")
        scene.create_entity("Child", parent_id=entity.entity_id)
        panel.render(scene)
        panel._tree.item(entity.entity_id, open=True)
        panel.select(entity.entity_id)
        self.root.update()

        panel.render(scene)
        self.root.update()

        self.assertTrue(panel._tree.exists(entity.entity_id))
        self.assertEqual(panel._tree.selection(), (entity.entity_id,))
        self.assertEqual(panel._tree.item(entity.entity_id, "text"), "[PLY] Player")
        self.assertTrue(panel._tree.item(entity.entity_id, "open"))

    def test_hierarchy_marks_camera_and_player_roles(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Roles")
        camera = scene.create_entity("Camera")
        player = scene.create_entity("Player")
        compact_player = scene.create_entity("Player Marker")
        panel.render(scene)

        self.assertEqual(panel._tree.item(camera.entity_id, "text"), "[CAM] Camera")
        self.assertEqual(panel._tree.item(player.entity_id, "text"), "[PLY] Player")
        self.assertEqual(panel._tree.item(compact_player.entity_id, "text"), "[PLY] Player Marker")
        compact_player.enabled = False
        panel.render(scene)
        self.assertEqual(panel._tree.item(compact_player.entity_id, "text"), "[PLY] Player Marker")
        self.assertEqual(panel._tree.item(compact_player.entity_id, "tags"), ("disabled",))

    def test_inspector_has_scrollable_content_and_empty_state(self) -> None:
        panel = InspectorPanel(self.root)
        panel.pack(fill="both", expand=True)
        panel.render(None)
        self.assertEqual(panel._current_entity_id, None)
        self.assertTrue(panel._scroll_canvas.winfo_exists())

        entity = Scene("Scene").create_entity("Player")
        entity.add_component(TransformComponent())
        panel.render(entity)
        self.root.update_idletasks()
        self.assertEqual(panel._current_entity_id, entity.entity_id)
        self.assertIsNotNone(panel._scroll_canvas.bbox("all"))

    def test_viewport_handles_disabled_entities_and_empty_scene(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Viewport")
        visible = scene.create_entity("Player")
        visible.add_component(TransformComponent())
        hidden = scene.create_entity("Hidden")
        hidden.enabled = False
        hidden.add_component(TransformComponent())

        panel.render(scene, visible.entity_id)
        self.root.update_idletasks()
        self.assertTrue(panel._canvas.find_withtag(f"entity:{visible.entity_id}"))
        self.assertFalse(panel._canvas.find_withtag(f"entity:{hidden.entity_id}"))

        panel.render(None)
        self.assertTrue(panel._canvas.find_withtag("all"))

    def test_viewport_hides_nonvisual_entities_without_transforms(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Controller")
        controller = scene.create_entity("Game Controller")
        controller.add_component(ScriptComponent("project://controller.py", "Controller"))

        panel.render(scene)
        self.root.update_idletasks()

        self.assertFalse(panel._canvas.find_withtag(f"entity:{controller.entity_id}"))

    def test_viewport_hides_editor_markers_in_runtime_preview(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Runtime preview")
        camera = scene.create_entity("Camera")
        camera.add_component(TransformComponent())
        player = scene.create_entity("Player")
        player.add_component(TransformComponent())
        player.add_component(TextComponent("ball"))

        panel.render(scene, editor_overlays=False)
        self.root.update_idletasks()

        self.assertFalse(panel._canvas.find_withtag(f"entity:{camera.entity_id}"))
        self.assertTrue(panel._canvas.find_withtag(f"entity:{player.entity_id}"))

    def test_viewport_accepts_float_text_sizes(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Text")
        entity = scene.create_entity("Label")
        entity.add_component(TextComponent("Score", size=8.0, color=Color(1.0, 1.0, 1.0)))

        panel.render(scene)
        self.root.update_idletasks()

        self.assertTrue(panel._canvas.find_withtag(f"entity:{entity.entity_id}"))

    def test_viewport_uses_distinct_camera_and_player_shapes(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Roles")
        camera = scene.create_entity("Camera")
        player = scene.create_entity("Player")
        generic = scene.create_entity("Enemy")
        panel.render(scene)

        camera_types = {
            panel._canvas.type(item)
            for item in panel._canvas.find_withtag(f"entity:{camera.entity_id}")
        }
        player_types = {
            panel._canvas.type(item)
            for item in panel._canvas.find_withtag(f"entity:{player.entity_id}")
        }
        generic_types = {
            panel._canvas.type(item)
            for item in panel._canvas.find_withtag(f"entity:{generic.entity_id}")
        }
        self.assertIn("rectangle", camera_types)
        self.assertIn("oval", camera_types)
        self.assertIn("polygon", player_types)
        self.assertIn("oval", player_types)
        self.assertIn("line", player_types)
        self.assertIn("rectangle", generic_types)
        self.assertNotIn("oval", generic_types)

    def test_viewport_restores_marker_designs_after_disable_enable(self) -> None:
        panel = ViewportPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Toggle Roles")
        camera = scene.create_entity("Camera")
        player = scene.create_entity("Player")
        compact_camera = scene.create_entity("Camera Marker")
        compact_player = scene.create_entity("Player Marker")

        panel.render(scene)
        self.root.update_idletasks()

        def item_types(entity_id: str) -> tuple[str, ...]:
            types: list[str] = []
            for item in panel._canvas.find_withtag(f"entity:{entity_id}"):
                item_type = panel._canvas.type(item)
                if item_type is not None:
                    types.append(str(item_type))
            return tuple(sorted(types))

        initial_types = {
            entity.entity_id: item_types(entity.entity_id)
            for entity in (camera, player, compact_camera, compact_player)
        }
        for entity in (camera, player, compact_camera, compact_player):
            entity.enabled = False
        panel.render(scene)
        self.assertFalse(panel._canvas.find_withtag(f"entity:{camera.entity_id}"))
        for entity in (camera, player, compact_camera, compact_player):
            entity.enabled = True
        panel.render(scene)
        restored_types = {
            entity.entity_id: item_types(entity.entity_id)
            for entity in (camera, player, compact_camera, compact_player)
        }
        self.assertEqual(restored_types, initial_types)


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class EditorWindowLayoutTests(unittest.TestCase):
    @unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
    def test_add_entity_does_not_recurse_through_tree_selection(self) -> None:
        window = EditorWindow(Engine())
        try:
            self.assertIsInstance(window._assets, AssetBrowserPanel)
            before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]
            window._act_add_entity()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before + 1)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_repeated_add_with_existing_selection_stays_responsive(self) -> None:
        window = EditorWindow(Engine())
        try:
            before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]
            window._act_add_entity()
            window._root.update()
            window._act_add_entity()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before + 2)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_reselecting_same_entity_does_not_reenter_presentation(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._act_add_entity()
            window._root.update()
            selected_id = window._selected_id
            self.assertIsNotNone(selected_id)
            for _ in range(5):
                window._hierarchy.select(selected_id)
                window._root.update()
            self.assertEqual(window._selected_id, selected_id)
        finally:
            window._on_close()

    def test_delete_disables_after_selected_entity_is_removed(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._act_add_entity()
            window._root.update()
            entity_id = window._selected_id
            self.assertTrue(window._actions.is_enabled("delete_entity"))
            if entity_id is None:
                self.fail("Add did not select the created entity")
            window._on_hierarchy_delete(entity_id)
            window._root.update()
            self.assertFalse(window._actions.is_enabled("delete_entity"))
        finally:
            window._on_close()

    def test_new_scene_clears_delete_action_state(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._act_add_entity()
            window._root.update()
            self.assertTrue(window._actions.is_enabled("delete_entity"))
            window._act_new_scene()
            window._root.update()
            self.assertIsNone(window._selected_id)
            self.assertFalse(window._actions.is_enabled("delete_entity"))
        finally:
            window._on_close()

    def test_entity_mutations_are_blocked_while_playing(self) -> None:
        window = EditorWindow(Engine())
        try:
            edit_scene = window._engine.edit_scene
            before = len(edit_scene.entities)  # type: ignore[union-attr]
            window._act_play()
            window._root.update()
            self.assertFalse(window._actions.is_enabled("add_entity"))
            self.assertFalse(window._actions.is_enabled("delete_entity"))
            window._act_add_entity()
            window._root.update()
            self.assertEqual(len(edit_scene.entities), before)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_inspector_mutations_do_not_touch_edit_scene_while_playing(self) -> None:
        window = EditorWindow(Engine())
        try:
            edit_scene = window._engine.edit_scene
            entity = edit_scene.roots()[0]  # type: ignore[union-attr]
            transform = entity.get_component(TransformComponent)
            self.assertIsNotNone(transform)
            original_name = entity.name
            original_enabled = entity.enabled
            original_x = transform.x  # type: ignore[union-attr]
            window._act_play()
            window._root.update()
            window._on_transform_change(entity.entity_id, "x", original_x + 100)  # type: ignore[union-attr]
            window._on_entity_rename(entity.entity_id, "Edited During Play")
            window._on_entity_toggle(entity.entity_id, not original_enabled)
            self.assertEqual(transform.x, original_x)  # type: ignore[union-attr]
            self.assertEqual(entity.name, original_name)
            self.assertEqual(entity.enabled, original_enabled)
        finally:
            window._on_close()

    def test_shell_registers_styles_and_resizable_panes(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._root.update_idletasks()
            self.assertGreaterEqual(window._root.winfo_width(), 980)
            self.assertGreaterEqual(window._root.winfo_height(), 640)
            self.assertTrue(window._content_paned.winfo_exists())
            self.assertTrue(window._main_paned.winfo_exists())
            self.assertGreaterEqual(window._inspector_host.winfo_width(), 260)
            self.assertGreaterEqual(window._hierarchy_host.winfo_width(), 190)
            self.assertGreaterEqual(window._console_host.winfo_height(), 96)
            self.assertEqual(
                window._style.lookup("Editor.Treeview", "background"), COLORS["surface"]
            )
        finally:
            window._on_close()

    @unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
    def test_shell_keeps_sidebars_usable_when_resized(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._root.geometry("980x640")
            window._root.update()
            self.assertGreaterEqual(window._inspector_host.winfo_width(), 260)
            narrow_viewport = window._viewport_host.winfo_width()
            window._root.geometry("1440x900")
            window._root.update()
            self.assertGreater(window._viewport_host.winfo_width(), narrow_viewport)
            self.assertGreaterEqual(window._console_host.winfo_height(), 96)
        finally:
            window._on_close()


class StyleRegistrationTests(unittest.TestCase):
    def test_editor_tree_and_entry_styles_are_registered(self) -> None:
        class FakeStyle:
            def __init__(self) -> None:
                self.configured: dict[str, dict[str, object]] = {}
                self.mapped: dict[str, dict[str, object]] = {}

            def configure(self, name: str, **options: object) -> None:
                self.configured[name] = options

            def map(self, name: str, **options: object) -> None:
                self.mapped[name] = options

        style = FakeStyle()
        configure_app_styles(style)
        self.assertIn("Editor.Treeview", style.configured)
        self.assertIn("Editor.TEntry", style.configured)
        self.assertIn("Editor.TCheckbutton", style.configured)


if __name__ == "__main__":
    unittest.main()
