"""Real-widget regression tests for the mature editor shell."""

import tkinter as tk
import unittest
from contextlib import suppress

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.scene import Scene
from expra_engine.ui.editor_window import EditorWindow
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel
from expra_engine.ui.styles import COLORS, configure_app_styles


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


DISPLAY_AVAILABLE = _display_available()


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class EditorPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
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


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class EditorWindowLayoutTests(unittest.TestCase):
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
            self.assertEqual(window._style.lookup("Editor.Treeview", "background"), COLORS["surface"])
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
