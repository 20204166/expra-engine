"""Real-widget regression tests for the mature editor shell."""

import tkinter as tk
import unittest
from contextlib import suppress
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from expra_engine.core.component import TransformComponent
from expra_engine.core.component_schema import PropertyDescriptor
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.editor.assets import AssetEntry
from expra_engine.editor.runtime_preview import RuntimePreviewLoop
from expra_engine.filesystem import ResourceId
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent
from expra_engine.ui.asset_browser import AssetBrowserPanel
from expra_engine.ui.editor_window import EditorWindow
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel
from expra_engine.ui.styles import COLORS, configure_app_styles, editor_entity_kind
from expra_engine.ui.viewport import ViewportPanel
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()


def _tk_call_counters() -> dict[str, int]:
    return {"insert": 0, "delete": 0, "item": 0, "move": 0}


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

    def test_asset_unchanged_refresh_reuses_rows_and_browser_state(self) -> None:
        panel = AssetBrowserPanel(self.root, root_directory=self.root_path, coordinator=None)
        panel.pack(fill="both", expand=True)
        folder_path = self.root_path / "textures"
        hero_path = folder_path / "hero.png"
        folder = AssetEntry(folder_path, "textures", True, ResourceId.parse("assets://textures"))
        hero = AssetEntry(
            hero_path, "hero.png", False, ResourceId.parse("assets://textures/hero.png")
        )
        panel.render_entries((folder, hero))
        folder_id = panel._iid_for_path(folder_path)
        hero_id = panel._iid_for_path(hero_path)
        panel._tree.item(folder_id, open=True)
        panel._tree.selection_set(hero_id)
        panel._on_select()

        calls = _tk_call_counters()
        for name in calls:
            original = getattr(panel._tree, name)

            def count_call(
                *args: Any, _original: Any = original, _name: str = name, **kwargs: Any
            ) -> Any:
                calls[_name] += 1
                return _original(*args, **kwargs)

            setattr(panel._tree, name, count_call)

        refreshed_folder = AssetEntry(
            folder_path, "textures", True, ResourceId.parse("assets://textures")
        )
        refreshed_hero = AssetEntry(
            hero_path, "hero.png", False, ResourceId.parse("assets://textures/hero.png")
        )
        panel.render_entries((refreshed_folder, refreshed_hero))
        for _ in range(4):
            panel.render_entries((refreshed_folder, refreshed_hero))

        self.assertEqual(calls, {"insert": 0, "delete": 0, "item": 0, "move": 0})
        self.assertEqual(len(panel._path_iids), len(panel._entries) + 1)
        self.assertTrue(panel._tree.item(folder_id, "open"))
        self.assertEqual(panel._tree.selection(), (hero_id,))
        self.assertEqual(panel.selected_entry, refreshed_hero)

    def test_asset_small_delta_preserves_surviving_selection_and_expansion(self) -> None:
        panel = AssetBrowserPanel(self.root, root_directory=self.root_path, coordinator=None)
        panel.pack(fill="both", expand=True)
        folder_path = self.root_path / "textures"
        first_path = folder_path / "a.png"
        last_path = folder_path / "c.png"
        added_path = folder_path / "b.png"
        folder = AssetEntry(folder_path, "textures", True, ResourceId.parse("assets://textures"))
        first = AssetEntry(first_path, "a.png", False, ResourceId.parse("assets://textures/a.png"))
        last = AssetEntry(last_path, "c.png", False, ResourceId.parse("assets://textures/c.png"))
        panel.render_entries((folder, first, last))
        folder_id = panel._iid_for_path(folder_path)
        first_id = panel._iid_for_path(first_path)
        panel._tree.item(folder_id, open=True)
        panel._tree.selection_set(first_id)
        panel._on_select()

        calls = _tk_call_counters()
        for name in calls:
            original = getattr(panel._tree, name)

            def count_call(
                *args: Any, _original: Any = original, _name: str = name, **kwargs: Any
            ) -> Any:
                calls[_name] += 1
                return _original(*args, **kwargs)

            setattr(panel._tree, name, count_call)

        added = AssetEntry(added_path, "b.png", False, ResourceId.parse("assets://textures/b.png"))
        refreshed_first = AssetEntry(
            first_path, "a.png", False, ResourceId.parse("assets://textures/a.png")
        )
        refreshed_last = AssetEntry(
            last_path, "c.png", False, ResourceId.parse("assets://textures/c.png")
        )
        panel.render_entries((folder, refreshed_first, added, refreshed_last))

        self.assertEqual(calls, {"insert": 1, "delete": 0, "item": 0, "move": 0})
        self.assertEqual(
            panel._tree.get_children(folder_id),
            tuple(panel._iid_for_path(path) for path in (first_path, added_path, last_path)),
        )
        self.assertEqual(panel._tree.selection(), (first_id,))
        self.assertTrue(panel._tree.item(folder_id, "open"))
        self.assertIs(panel.selected_entry, refreshed_first)

    def test_asset_removal_clears_selection_and_folder_classification_updates(self) -> None:
        panel = AssetBrowserPanel(self.root, root_directory=self.root_path, coordinator=None)
        panel.pack(fill="both", expand=True)
        node_path = self.root_path / "node"
        file_entry = AssetEntry(node_path, "node", False, ResourceId.parse("assets://node"))
        panel.render_entries((file_entry,))
        node_id = panel._iid_for_path(node_path)
        panel._tree.selection_set(node_id)
        panel._on_select()

        folder_entry = AssetEntry(node_path, "node", True, ResourceId.parse("assets://node"))
        panel.render_entries((folder_entry,))
        self.assertEqual(panel._tree.set(node_id, "kind"), "Folder")
        self.assertEqual(panel._tree.selection(), (node_id,))
        self.assertIs(panel.selected_entry, folder_entry)

        panel.render_entries(())
        self.assertEqual(panel._tree.selection(), ())
        self.assertIsNone(panel.selected_entry)

    def test_asset_folder_navigation_keeps_child_after_parent_branch_is_removed(self) -> None:
        panel = AssetBrowserPanel(self.root, root_directory=self.root_path, coordinator=None)
        panel.pack(fill="both", expand=True)
        folder_path = self.root_path / "textures"
        image_path = folder_path / "hero.png"
        folder = AssetEntry(folder_path, "textures", True, ResourceId.parse("assets://textures"))
        image = AssetEntry(
            image_path, "hero.png", False, ResourceId.parse("assets://textures/hero.png")
        )
        panel.render_entries((folder, image))

        panel._current_directory = folder_path
        panel.render_entries((image,))

        image_id = panel._iid_for_path(image_path)
        self.assertTrue(panel._tree.exists(image_id))
        self.assertEqual(panel._tree.parent(image_id), "")
        self.assertEqual(panel._tree.get_children(""), (image_id,))

    def test_asset_population_uses_one_stable_observability_target(self) -> None:
        observer = ObservabilityWatcher()
        panel = AssetBrowserPanel(
            self.root,
            root_directory=self.root_path,
            coordinator=None,
            observer=observer,
        )
        entry = AssetEntry(
            self.root_path / "hero.png",
            "hero.png",
            False,
            ResourceId.parse("assets://hero.png"),
        )

        panel.render_entries((entry,))

        metrics = observer.snapshot().metrics
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].target, "ui:assets:populate")
        self.assertEqual(metrics[0].count, 1)

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

    def test_unchanged_hierarchy_render_does_not_update_or_move_rows(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Unchanged")
        parent = scene.create_entity("Parent")
        for index in range(20):
            scene.create_entity(f"Child {index}", parent_id=parent.entity_id)
        panel.render(scene)
        self.root.update_idletasks()

        calls = {"item": 0, "move": 0}
        for name in calls:
            original = getattr(panel._tree, name)

            def count_call(
                *args: Any, _original: Any = original, _name: str = name, **kwargs: Any
            ) -> Any:
                calls[_name] += 1
                return _original(*args, **kwargs)

            setattr(panel._tree, name, count_call)

        panel.render(scene)

        self.assertEqual(calls, {"item": 0, "move": 0})

    def test_hierarchy_reconciles_one_rename_without_moving_unchanged_rows(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Rename")
        entities = [scene.create_entity(f"Entity {index}") for index in range(10)]
        panel.render(scene)
        calls = {"item": 0, "move": 0}
        for name in calls:
            original = getattr(panel._tree, name)

            def count_call(
                *args: Any, _original: Any = original, _name: str = name, **kwargs: Any
            ) -> Any:
                calls[_name] += 1
                return _original(*args, **kwargs)

            setattr(panel._tree, name, count_call)

        entities[4].name = "Renamed"
        panel.render(scene)

        self.assertEqual(calls, {"item": 1, "move": 0})
        self.assertEqual(panel._tree.item(entities[4].entity_id, "text"), "Renamed")

    def test_hierarchy_reconciles_add_delete_reparent_and_enabled_state(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Structural diff")
        parent_a = scene.create_entity("Parent A")
        parent_b = scene.create_entity("Parent B")
        child = scene.create_entity("Child", parent_id=parent_a.entity_id)
        panel.render(scene)

        calls = _tk_call_counters()
        originals = {name: getattr(panel._tree, name) for name in calls}

        def watch(name: str) -> None:
            original = originals[name]

            def count_call(*args: Any, **kwargs: Any) -> Any:
                calls[name] += 1
                return original(*args, **kwargs)

            setattr(panel._tree, name, count_call)

        for name in calls:
            watch(name)

        added = scene.create_entity("Added")
        panel.render(scene)
        self.assertEqual(calls, {"insert": 1, "delete": 0, "item": 0, "move": 0})
        calls.update(_tk_call_counters())

        scene.set_entity_parent(child.entity_id, parent_b.entity_id)
        panel.render(scene)
        self.assertEqual(calls, {"insert": 0, "delete": 0, "item": 0, "move": 1})
        self.assertEqual(panel._tree.parent(child.entity_id), parent_b.entity_id)
        calls.update(_tk_call_counters())

        added.enabled = False
        panel.render(scene)
        self.assertEqual(calls, {"insert": 0, "delete": 0, "item": 1, "move": 0})
        self.assertEqual(panel._tree.item(added.entity_id, "tags"), ("disabled",))
        calls.update(_tk_call_counters())

        scene.remove_entity(added.entity_id)
        panel.render(scene)
        self.assertEqual(calls, {"insert": 0, "delete": 1, "item": 0, "move": 0})
        self.assertFalse(panel._tree.exists(added.entity_id))

    def test_hierarchy_reorders_only_the_reinserted_sibling(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Sibling order")
        entities = [scene.create_entity(f"Entity {index}") for index in range(3)]
        panel.render(scene)
        moves = 0
        original_move = panel._tree.move

        def count_move(*args: Any, **kwargs: Any) -> Any:
            nonlocal moves
            moves += 1
            return original_move(*args, **kwargs)

        with patch.object(panel._tree, "move", side_effect=count_move):
            scene.remove_entity(entities[0].entity_id)
            scene.add_entity(entities[0])
            panel.render(scene)

        self.assertEqual(
            panel._tree.get_children(""),
            (entities[1].entity_id, entities[2].entity_id, entities[0].entity_id),
        )
        self.assertEqual(moves, 1)

    def test_hierarchy_reparents_survivor_out_of_removed_treeview_subtree(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Parent deletion and reparent")
        removed_parent = scene.create_entity("Removed Parent")
        surviving_parent = scene.create_entity("Surviving Parent")
        child = scene.create_entity("Child", parent_id=removed_parent.entity_id)
        panel.render(scene)

        scene.set_entity_parent(child.entity_id, surviving_parent.entity_id)
        scene.remove_entity(removed_parent.entity_id)
        panel.render(scene)

        self.assertFalse(panel._tree.exists(removed_parent.entity_id))
        self.assertTrue(panel._tree.exists(child.entity_id))
        self.assertEqual(panel._tree.parent(child.entity_id), surviving_parent.entity_id)

    def test_hierarchy_render_handles_more_than_one_thousand_nested_entities(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Deep")
        parent_id = None
        depth = 1_200
        for index in range(depth):
            entity = scene.create_entity(f"Node {index}", parent_id=parent_id)
            parent_id = entity.entity_id

        panel.render(scene)

        self.assertEqual(len(panel._entity_ids), depth)
        self.assertEqual(panel._tree.get_children("")[0], scene.roots()[0].entity_id)

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

    def test_hierarchy_marks_scene_instance_roots_and_materialized_children(self) -> None:
        panel = HierarchyPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Instances")
        root = scene.create_entity("Room Instance")
        root.add_component(SceneInstanceComponent("scenes/room.json"))
        child = scene.create_entity("Wall", parent_id=root.entity_id)
        scene._set_instance_children(root.entity_id, {child.entity_id})

        panel.render(scene)

        self.assertEqual(panel._tree.item(root.entity_id, "text"), "[INST] Room Instance")
        self.assertEqual(panel._tree.item(child.entity_id, "text"), "[in] Wall")

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

    def test_inspector_reuses_controls_and_updates_values_for_matching_schema(self) -> None:
        panel = InspectorPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Inspector reuse")
        first = scene.create_entity("First")
        first.add_component(TransformComponent(x=1.0))
        second = scene.create_entity("Second")
        second.add_component(TransformComponent(x=2.0))
        panel.render(first)
        self.root.update_idletasks()
        name_var = panel._name_var
        transform_vars = dict(panel._component_vars)
        content_children = tuple(panel._content.winfo_children())

        panel.render(second)

        self.assertIs(panel._name_var, name_var)
        assert panel._name_var is not None
        self.assertEqual(panel._name_var.get(), "Second")
        for field, variable in transform_vars.items():
            self.assertIs(panel._component_vars[field], variable)
        self.assertEqual(panel._component_vars[(0, "x")].get(), "2.0")
        self.assertEqual(tuple(panel._content.winfo_children()), content_children)

        second.get_component(TransformComponent).x = 7.0  # type: ignore[union-attr]
        panel.render(second)
        self.assertEqual(panel._component_vars[(0, "x")].get(), "7.0")
        self.assertEqual(tuple(panel._content.winfo_children()), content_children)

    def test_reused_component_entry_commits_to_the_current_entity(self) -> None:
        changed: list[tuple[Any, ...]] = []
        panel = InspectorPanel(
            self.root,
            on_component_change=lambda *args: changed.append(args),
        )
        panel.pack(fill="both", expand=True)
        scene = Scene("Component callbacks")
        first = scene.create_entity("First")
        first.add_component(TransformComponent())
        first.add_component(ColliderComponent(width=12.5))
        second = scene.create_entity("Second")
        second.add_component(TransformComponent())
        second.add_component(ColliderComponent(width=20.0))
        panel.render(first)
        entry = panel._component_widgets[(1, "width")]

        panel.render(second)

        self.assertIs(panel._component_widgets[(1, "width")], entry)
        self.assertEqual(entry.get(), "20.0")
        entry.focus_force()
        self.root.update()
        entry.delete(0, tk.END)
        entry.insert(0, "37.5")
        entry.event_generate("<Return>", when="now")
        self.assertEqual(changed, [(second.entity_id, "collider", "width", 37.5)])

    def test_reused_script_controls_commit_to_the_current_entity(self) -> None:
        changed: list[tuple[Any, ...]] = []
        panel = InspectorPanel(
            self.root,
            on_script_value_change=lambda *args: changed.append(args),
        )
        panel.pack(fill="both", expand=True)
        scene = Scene("Script callbacks")
        first = scene.create_entity("First")
        first.add_component(TransformComponent())
        first.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={"speed": 2, "enabled": False},
            )
        )
        second = scene.create_entity("Second")
        second.add_component(TransformComponent())
        second.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={"speed": 8, "enabled": False},
            )
        )
        panel.render(first)
        speed_entry = cast(ttk.Entry, panel._script_widgets[(1, "speed")])
        enabled_check = cast(ttk.Checkbutton, panel._script_widgets[(1, "enabled")])

        panel.render(second)

        self.assertIs(panel._script_widgets[(1, "speed")], speed_entry)
        self.assertIs(panel._script_widgets[(1, "enabled")], enabled_check)
        self.assertEqual(speed_entry.get(), "8")
        speed_entry.focus_force()
        self.root.update()
        speed_entry.delete(0, tk.END)
        speed_entry.insert(0, "11")
        speed_entry.event_generate("<Return>", when="now")
        enabled_check.invoke()
        self.assertEqual(
            changed,
            [
                (second.entity_id, 1, "speed", 11),
                (second.entity_id, 1, "enabled", True),
            ],
        )

    def test_inspector_rebuilds_when_component_or_script_schema_changes(self) -> None:
        panel = InspectorPanel(self.root)
        panel.pack(fill="both", expand=True)
        entity = Scene("Schema changes").create_entity("Player")
        entity.add_component(TransformComponent())
        panel.render(entity)
        original_name_var = panel._name_var

        collider = ColliderComponent()
        entity.add_component(collider)
        panel.render(entity)
        self.assertIsNot(panel._name_var, original_name_var)
        self.assertIn((1, "width"), panel._component_vars)

        script = ScriptComponent("project://scripts/probe.py", "Probe", exposed_values={"speed": 1})
        entity.add_component(script)
        panel.render(entity)
        self.assertIn((2, "speed"), panel._script_vars)
        old_speed = panel._script_vars[(2, "speed")]
        script.exposed_values["enabled"] = False
        panel.render(entity)
        self.assertIsNot(panel._script_vars[(2, "speed")], old_speed)
        self.assertIn((2, "enabled"), panel._script_vars)

        entity.remove_component(collider)
        panel.render(entity)
        self.assertNotIn((1, "width"), panel._component_vars)

    def test_inspector_defers_same_schema_selection_while_a_field_is_focused(self) -> None:
        panel = InspectorPanel(self.root)
        panel.pack(fill="both", expand=True)
        scene = Scene("Inspector focus")
        first = scene.create_entity("First")
        first.add_component(TransformComponent())
        second = scene.create_entity("Second")
        second.add_component(TransformComponent(x=9.0))
        changed: list[tuple[Any, ...]] = []
        panel._on_component_change = lambda *args: changed.append(args)
        panel.render(first)
        variable = panel._component_vars[(0, "x")]
        old_name_var = panel._name_var
        entry = panel._component_widgets[(0, "x")]
        entry.focus_force()
        self.root.update()
        variable.set("3.")

        panel.render(second)

        self.assertIs(panel._name_var, old_name_var)
        self.assertEqual(panel._current_entity_id, first.entity_id)
        self.assertEqual(variable.get(), "3.")
        self.assertEqual(self.root.focus_get(), entry)

        self.root.focus_force()
        self.root.update()
        self.assertEqual(changed, [(first.entity_id, "transform", "x", 3.0)])
        self.assertEqual(panel._current_entity_id, second.entity_id)
        self.assertEqual(panel._component_vars[(0, "x")].get(), "9.0")

    def test_inspector_preserves_scroll_position_across_schema_rebuild(self) -> None:
        self.root.geometry("360x240")
        panel = InspectorPanel(self.root)
        panel.pack(fill="both", expand=True)
        first = Scene("Scroll").create_entity("First")
        first.add_component(TransformComponent())
        first.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={f"field_{index}": index for index in range(30)},
            )
        )
        second = Scene("Scroll").create_entity("Second")
        second.add_component(TransformComponent())
        second.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={
                    **{f"field_{index}": index for index in range(30)},
                    "new_field": 1,
                },
            )
        )
        panel.render(first)
        self.root.update()
        panel._scroll_canvas.yview_moveto(0.7)
        self.root.update_idletasks()

        panel.render(second)
        self.root.update()

        self.assertGreater(panel._scroll_canvas.yview()[0], 0.6)

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

    def test_canvas_dispatch_keeps_primitive_selection_multi_select_and_drag(self) -> None:
        window = EditorWindow(Engine())
        try:
            scene = Scene("Canvas dispatch")
            entities = []
            for name, x in (("First", -5.0), ("Second", 5.0)):
                entity = scene.create_entity(name)
                entity.add_component(TransformComponent(x=x))
                entity.add_component(PrimitiveComponent())
                entities.append(entity)
            window._engine.set_scene(scene)
            window._selected_ids = ()
            window._present_all()
            window._root.update()
            canvas = window._viewport._canvas

            def click(entity: Any, state: int = 0) -> tuple[int, int]:
                items = canvas.find_withtag(f"entity:{entity.entity_id}")
                self.assertTrue(items)
                bounds = canvas.bbox(f"entity:{entity.entity_id}")
                self.assertIsNotNone(bounds)
                assert bounds is not None
                x = (bounds[0] + bounds[2]) // 2
                y = (bounds[1] + bounds[3]) // 2
                canvas.event_generate("<Button-1>", x=x, y=y, state=state, when="now")
                window._root.update()
                return x, y

            first_point = click(entities[0])
            self.assertEqual(window._selected_ids, (entities[0].entity_id,))
            canvas.event_generate(
                "<ButtonRelease-1>", x=first_point[0], y=first_point[1], when="now"
            )
            window._root.update()

            click(entities[1], state=0x0001)
            self.assertEqual(
                window._selected_ids,
                (entities[0].entity_id, entities[1].entity_id),
            )
            self.assertTrue(window._viewport._spatial_edit.is_dragging_transform)
            window._viewport._spatial_edit.cancel_drag()
        finally:
            window._on_close()

    def test_canvas_dispatch_keeps_marker_click_and_selection_color_updates(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._root.update()
            scene = Scene("Marker dispatch")
            marker = scene.create_entity("Camera")
            marker.add_component(TransformComponent())
            window._engine.set_scene(scene)
            window._selected_ids = ()
            window._present_all()
            window._root.update()
            canvas = window._viewport._canvas
            marker_items = canvas.find_withtag(f"entity:{marker.entity_id}")
            self.assertTrue(marker_items)
            marker_body = marker_items[0]
            self.assertEqual(canvas.itemcget(marker_body, "fill"), COLORS["camera"])

            bounds = canvas.bbox(marker_body)
            self.assertIsNotNone(bounds)
            assert bounds is not None
            canvas.event_generate(
                "<Button-1>",
                x=(bounds[0] + bounds[2]) // 2,
                y=(bounds[1] + bounds[3]) // 2,
                when="now",
            )
            window._root.update()

            self.assertEqual(window._selected_ids, (marker.entity_id,))
            self.assertEqual(canvas.itemcget(marker_body, "fill"), COLORS["camera_active"])
        finally:
            window._on_close()


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

    def test_selection_updates_tree_selection_without_rendering_hierarchy(self) -> None:
        window = EditorWindow(Engine())
        try:
            scene = window._engine.edit_scene
            self.assertIsNotNone(scene)
            entity_id = scene.entities[0].entity_id  # type: ignore[union-attr]
            window._observer.reset()

            window._on_hierarchy_select((entity_id,))

            metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            self.assertEqual(metrics.get("ui:render:hierarchy", 0), 0)
            self.assertEqual(metrics.get("ui:render:inspector"), 1)
            self.assertEqual(metrics.get("ui:render:viewport"), 1)
            self.assertEqual(window._hierarchy._tree.selection(), (entity_id,))
        finally:
            window._on_close()

    def test_selection_refresh_updates_viewport_overlay_without_reextracting_scene(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._root.update()
            scene = Scene("Selection overlay")
            entities = []
            for index in range(12):
                entity = scene.create_entity(f"Entity {index}")
                entity.add_component(TransformComponent(x=float(index * 2)))
                entity.add_component(PrimitiveComponent())
                entities.append(entity)
            window._engine.set_scene(scene)
            window._selected_ids = ()
            window._present_all()
            window._root.update_idletasks()
            previous_frame = window._viewport._target.frame
            previous_items = tuple(window._viewport._canvas_items)
            window._observer.reset()

            window._on_hierarchy_select((entities[4].entity_id,))
            window._root.update_idletasks()

            self.assertIs(window._viewport._target.frame, previous_frame)
            self.assertEqual(tuple(window._viewport._canvas_items), previous_items)
            self.assertIn(entities[4].entity_id, window._viewport._items_by_id)
            self.assertIn(entities[4].entity_id, window._viewport._canvas_items)
            self.assertTrue(
                window._viewport._canvas.find_withtag("selection"),
                (window._viewport._selected_id, window._viewport._target.selected_id),
            )
            self.assertEqual(window._viewport._selected_id, entities[4].entity_id)
            metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            self.assertEqual(metrics.get("render:extract", 0), 0)
            self.assertEqual(metrics.get("ui:render:viewport"), 1)
        finally:
            window._on_close()

    def test_add_entity_commits_each_panel_once(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._observer.reset()

            window._act_add_entity()

            metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            for target in (
                "ui:render:hierarchy",
                "ui:render:inspector",
                "ui:render:viewport",
                "ui:render:toolbar",
            ):
                with self.subTest(target=target):
                    self.assertEqual(metrics.get(target), 1)
            self.assertEqual(window._hierarchy._tree.selection(), (window._selected_id,))
        finally:
            window._on_close()

    def test_script_attach_and_remove_present_inspector_once(self) -> None:
        window = EditorWindow(Engine())
        try:
            entity = window._engine.edit_scene.entities[0]  # type: ignore[union-attr]
            window._on_hierarchy_select((entity.entity_id,))

            window._observer.reset()
            with (
                patch(
                    "expra_engine.ui.editor_window.simpledialog.askstring",
                    side_effect=("project://scripts/example.py", "ExampleBehaviour"),
                ),
                patch(
                    "expra_engine.ui.editor_window.ScriptRegistry.resolve",
                    return_value=SimpleNamespace(exposed_schema=lambda: {}),
                ),
            ):
                window._act_attach_script()
            attach_metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            self.assertEqual(attach_metrics.get("ui:render:inspector"), 1)
            self.assertLessEqual(attach_metrics.get("ui:render:viewport", 0), 1)

            window._observer.reset()
            window._act_remove_script()
            remove_metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            self.assertEqual(remove_metrics.get("ui:render:inspector"), 1)
            self.assertLessEqual(remove_metrics.get("ui:render:viewport", 0), 1)
        finally:
            window._on_close()

    def test_duplicate_selection_presents_once_and_selects_new_rows(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids: list[str] = []
            for _ in range(2):
                window._act_add_entity()
                window._root.update_idletasks()
                assert window._selected_id is not None
                ids.append(window._selected_id)
            window._on_viewport_entity_click(tuple(ids), False)
            window._observer.reset()

            window._act_duplicate_selection()

            metrics = {
                metric.target: metric.count for metric in window._observer.snapshot().metrics
            }
            for target in (
                "ui:render:hierarchy",
                "ui:render:inspector",
                "ui:render:viewport",
                "ui:render:toolbar",
            ):
                with self.subTest(target=target):
                    self.assertEqual(metrics.get(target), 1)
            self.assertEqual(len(window._selected_ids), 2)
            self.assertEqual(set(window._hierarchy._tree.selection()), set(window._selected_ids))
            self.assertTrue(
                all(window._hierarchy._tree.exists(entity_id) for entity_id in window._selected_ids)
            )
        finally:
            window._on_close()

    def test_undo_create_clears_removed_selection_and_action_state(self) -> None:
        window = EditorWindow(Engine())
        try:
            window._act_add_entity()
            self.assertTrue(window._selected_ids)

            window._act_undo()

            self.assertEqual(window._selected_ids, ())
            self.assertEqual(window._hierarchy._tree.selection(), ())
            self.assertFalse(window._actions.is_enabled("delete_entity"))
            self.assertFalse(window._actions.is_enabled("duplicate_selection"))
            self.assertIsNone(window._inspector._current_entity_id)
        finally:
            window._on_close()

    def test_delete_undo_and_redo_each_present_final_state_once(self) -> None:
        window = EditorWindow(Engine())
        try:
            entity_ids: list[str] = []
            for _ in range(2):
                window._act_add_entity()
                assert window._selected_id is not None
                entity_ids.append(window._selected_id)
            window._on_hierarchy_select(entity_ids)

            def assert_one_panel_commit() -> None:
                metrics = {
                    metric.target: metric.count for metric in window._observer.snapshot().metrics
                }
                for target in (
                    "ui:render:hierarchy",
                    "ui:render:inspector",
                    "ui:render:viewport",
                    "ui:render:toolbar",
                ):
                    with self.subTest(target=target):
                        self.assertEqual(metrics.get(target), 1)

            window._observer.reset()
            window._act_delete_entity()
            assert_one_panel_commit()
            self.assertEqual(window._selected_ids, ())

            window._observer.reset()
            window._act_undo()
            assert_one_panel_commit()

            window._observer.reset()
            window._act_redo()
            assert_one_panel_commit()
            self.assertEqual(window._selected_ids, ())
        finally:
            window._on_close()

    def test_play_stop_cycles_keep_canvas_callback_commands_bounded(self) -> None:
        window = EditorWindow(Engine())
        try:
            scene = Scene("Callback lifecycle")
            entity = scene.create_entity("Clickable")
            entity.add_component(TransformComponent())
            window._engine.set_scene(scene)
            window._selected_ids = ()
            window._present_all()
            window._root.update_idletasks()
            canvas = window._viewport._canvas
            baseline = len(getattr(canvas, "_tclCommands", None) or ())

            for _ in range(50):
                window._act_play()
                window._act_pause()
                window._act_play()
                window._act_stop()
                window._root.update_idletasks()

            self.assertLessEqual(len(getattr(canvas, "_tclCommands", None) or ()), baseline + 1)
            scene.remove_entity(entity.entity_id)
            window._present_all()
            scene.add_entity(entity)
            window._present_all()
            window._root.update_idletasks()
            self.assertLessEqual(len(getattr(canvas, "_tclCommands", None) or ()), baseline + 1)
            bounds = canvas.bbox(f"entity:{entity.entity_id}")
            self.assertIsNotNone(bounds)
            assert bounds is not None
            canvas.focus_force()
            canvas.event_generate(
                "<Button-1>",
                x=(bounds[0] + bounds[2]) // 2,
                y=(bounds[1] + bounds[3]) // 2,
                when="now",
            )
            window._root.update()
            self.assertEqual(window._selected_ids, (entity.entity_id,))
        finally:
            window._on_close()

    def test_scene_switches_release_retired_canvas_callback_commands(self) -> None:
        window = EditorWindow(Engine())
        try:
            scenes: list[Scene] = []
            for scene_index in range(2):
                scene = Scene(f"Scene {scene_index}")
                for entity_index in range(8):
                    entity = scene.create_entity(f"Entity {entity_index}")
                    entity.add_component(TransformComponent())
                scenes.append(scene)
            window._engine.set_scene(scenes[0])
            window._selected_ids = ()
            window._present_all()
            window._root.update_idletasks()
            canvas = window._viewport._canvas
            baseline = len(getattr(canvas, "_tclCommands", None) or ())

            for index in range(50):
                window._engine.set_scene(scenes[index % 2])
                window._selected_ids = ()
                window._present_all()
                window._root.update_idletasks()

            self.assertLessEqual(len(getattr(canvas, "_tclCommands", None) or ()), baseline + 1)
        finally:
            window._on_close()

    def test_editor_close_releases_canvas_callback_commands(self) -> None:
        window = EditorWindow(Engine())
        canvas = window._viewport._canvas

        window._on_close()

        self.assertFalse(getattr(canvas, "_tclCommands", None) or ())

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


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class MultiSelectionAndCommandTests(unittest.TestCase):
    def _add_entities(self, window: EditorWindow, count: int) -> list[str]:
        ids = []
        for _ in range(count):
            window._act_add_entity()
            window._root.update()
            assert window._selected_id is not None
            ids.append(window._selected_id)
        return ids

    def test_hierarchy_multi_select_syncs_to_window_and_viewport(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 3)
            window._hierarchy._tree.selection_set(ids[0], ids[2])
            window._root.update()
            self.assertEqual(set(window._selected_ids), {ids[0], ids[2]})
            self.assertEqual(window._viewport._selected_ids_set, frozenset({ids[0], ids[2]}))
        finally:
            window._on_close()

    def test_viewport_click_replaces_extends_and_toggles_selection(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 3)
            window._on_viewport_entity_click((ids[0],), False)
            self.assertEqual(window._selected_ids, (ids[0],))
            window._on_viewport_entity_click((ids[1],), True)  # shift-extend
            self.assertEqual(set(window._selected_ids), {ids[0], ids[1]})
            window._on_viewport_entity_click((ids[0],), True)  # shift toggles off
            self.assertEqual(window._selected_ids, (ids[1],))
            window._on_viewport_entity_click((ids[2],), False)  # plain click collapses
            self.assertEqual(window._selected_ids, (ids[2],))
        finally:
            window._on_close()

    def test_deleting_an_entity_drops_it_from_selection(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            window._on_viewport_entity_click((ids[0], ids[1]), False)
            self.assertEqual(set(window._selected_ids), {ids[0], ids[1]})
            window._on_hierarchy_delete(ids[0])
            window._root.update()
            self.assertEqual(window._selected_ids, (ids[1],))
        finally:
            window._on_close()

    def test_new_scene_sanitizes_selection(self) -> None:
        window = EditorWindow(Engine())
        try:
            self._add_entities(window, 1)
            self.assertTrue(window._selected_ids)
            window._act_new_scene()
            window._root.update()
            self.assertEqual(window._selected_ids, ())
            self.assertFalse(window._actions.is_enabled("duplicate_selection"))
        finally:
            window._on_close()

    def test_create_entity_is_undoable(self) -> None:
        window = EditorWindow(Engine())
        try:
            before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]
            before_history = len(window._command_stack.history)
            window._act_add_entity()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before + 1)  # type: ignore[union-attr]
            self.assertEqual(len(window._command_stack.history), before_history + 1)
            window._act_undo()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_transform_change_is_undoable_and_batches_all_fields(self) -> None:
        window = EditorWindow(Engine())
        try:
            entity_id = self._add_entities(window, 1)[0]
            entity = window._engine.edit_scene.find_entity(entity_id)  # type: ignore[union-attr]
            self.assertIsNotNone(entity)
            assert entity is not None
            transform = entity.get_component(TransformComponent)
            self.assertIsNotNone(transform)
            assert transform is not None
            history_before = len(window._command_stack.history)
            window._on_transform_change(entity_id, "x", 42.0)
            self.assertEqual(transform.x, 42.0)
            self.assertEqual(len(window._command_stack.history), history_before + 1)
            window._act_undo()
            self.assertEqual(transform.x, 0.0)
            # Same value again must be a no-op (no new history entry).
            window._on_transform_change(entity_id, "x", transform.x)
            self.assertEqual(len(window._command_stack.history), history_before)
        finally:
            window._on_close()

    def test_toggle_enabled_is_undoable(self) -> None:
        window = EditorWindow(Engine())
        try:
            entity_id = self._add_entities(window, 1)[0]
            entity = window._engine.edit_scene.find_entity(entity_id)  # type: ignore[union-attr]
            self.assertIsNotNone(entity)
            assert entity is not None
            self.assertTrue(entity.enabled)
            window._on_entity_toggle(entity_id, False)
            self.assertFalse(entity.enabled)
            window._act_undo()
            self.assertTrue(entity.enabled)
        finally:
            window._on_close()

    def test_duplicate_selection_single_and_multi_are_undoable(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 2)
            before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]
            window._on_viewport_entity_click((ids[0], ids[1]), False)
            history_before = len(window._command_stack.history)
            window._act_duplicate_selection()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before + 2)  # type: ignore[union-attr]
            self.assertEqual(len(window._command_stack.history), history_before + 1)
            self.assertEqual(len(window._selected_ids), 2)
            window._act_undo()
            self.assertEqual(len(window._engine.edit_scene.entities), before)  # type: ignore[union-attr]
            window._act_redo()
            self.assertEqual(len(window._engine.edit_scene.entities), before + 2)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_delete_selection_multi_is_one_undo_step(self) -> None:
        window = EditorWindow(Engine())
        try:
            ids = self._add_entities(window, 3)
            before = len(window._engine.edit_scene.entities)  # type: ignore[union-attr]
            window._on_viewport_entity_click((ids[0], ids[1]), False)
            history_before = len(window._command_stack.history)
            window._act_delete_entity()
            window._root.update()
            self.assertEqual(len(window._engine.edit_scene.entities), before - 2)  # type: ignore[union-attr]
            self.assertEqual(len(window._command_stack.history), history_before + 1)
            self.assertEqual(window._selected_ids, ())
            window._act_undo()
            self.assertEqual(len(window._engine.edit_scene.entities), before)  # type: ignore[union-attr]
        finally:
            window._on_close()

    def test_empty_canvas_click_deselects_through_real_tk_dispatch(self) -> None:
        """Regression test for the <Button-1>/<ButtonPress-1> binding collision:

        both were bound without add="+", so the second silently replaced the
        first and _on_click's empty-space deselect never fired in the live
        app (only entity-tag clicks worked). This exercises real event
        dispatch, not a direct method call, so it would have caught it.
        """
        window = EditorWindow(Engine())
        try:
            self._add_entities(window, 1)
            self.assertTrue(window._selected_ids)
            canvas = window._viewport._canvas
            canvas.focus_force()
            canvas.event_generate("<Button-1>", x=1, y=1, when="now")
            window._root.update()
            self.assertEqual(window._selected_ids, ())
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
