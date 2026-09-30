"""Qt main window -- the PySide6 frontend for ``EditorWindowCore``.

Coordinators, contribution registry, project workflow, panels and callbacks are
wired by the shared ``EditorWindowCore``. This module supplies the Qt shell:
QMainWindow, dock widgets, native Qt menus/toolbar, and the shell hooks the core
declares.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
)

from expra_engine.core.engine import Engine
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.interactions import (
    apply_component_change,
    remove_component,
    reparent_selection_to,
)
from expra_engine.editor.preferences import DEFAULT_PREFERENCES_PATH, PreferencesStore
from expra_engine.editor.qt.asset_browser import AssetBrowserPanel
from expra_engine.editor.qt.canvas import keysym_name
from expra_engine.editor.qt.console import ConsolePanel
from expra_engine.editor.qt.delivery import QtDeliveryQueue
from expra_engine.editor.qt.dialogs import QtDialogProvider
from expra_engine.editor.qt.export_dialog import ExportDialog
from expra_engine.editor.qt.hierarchy import HierarchyPanel
from expra_engine.editor.qt.inspector import InspectorPanel
from expra_engine.editor.qt.normal_map_preview import show_normal_map_preview
from expra_engine.editor.qt.normal_map_setup_dialog import NormalMapSetupDialog
from expra_engine.editor.qt.runtime_preview import QtRuntimePreviewLoop
from expra_engine.editor.qt.timer_delivery import QtTimerDelivery
from expra_engine.editor.qt.toolbar import build_toolbar
from expra_engine.editor.qt.viewport import ViewportPanel
from expra_engine.editor.window_core import EditorWindowCore
from expra_engine.editor.window_placement import WindowGeometry, initial_hierarchy_width
from expra_engine.ui.styles import accent_theme_colors

LOGGER = logging.getLogger(__name__)
_WINDOW_WIDTH = 1280
_WINDOW_HEIGHT = 800
_WINDOW_MIN_WIDTH = 980
_WINDOW_MIN_HEIGHT = 640
_INSPECTOR_WIDTH = 300
_BOTTOM_HEIGHT = 150


class _RuntimeKeyFilter(QObject):
    """Forward window key events to the running preview."""

    def __init__(self, window: EditorWindow) -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, watched: QObject, event: Any) -> bool:
        kind = event.type()
        if kind in (event.Type.KeyPress, event.Type.KeyRelease) and not event.isAutoRepeat():
            active = QApplication.activeWindow()
            if active is self._window:
                keysym = keysym_name(event.key(), event.text(), event.modifiers())
                phase = "press" if kind == event.Type.KeyPress else "release"
                self._window._forward_runtime_key(phase, keysym)
        return False


class EditorWindow(EditorWindowCore, QMainWindow):
    """Root editor window (Qt frontend)."""

    def __init__(
        self,
        engine: Engine,
        *,
        preferences_path: Path | None = None,
    ) -> None:
        QMainWindow.__init__(self)
        self._engine = engine
        self._active_document = ActiveDocument()
        self._is_closing = False
        self._pending_timer_ids: set[str] = set()
        self._autosave_after_id: Any = None
        self._viewport_camera_save_after_id: str | None = None
        self._preferences_path = preferences_path or DEFAULT_PREFERENCES_PATH
        self._preferences_store = PreferencesStore()
        self._preferences = self._preferences_store.load(self._preferences_path)

        self._root = self
        self.setWindowTitle("Expra Editor")
        self.resize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        saved_geometry = WindowGeometry.from_geometry_string(self._preferences.window_geometry or "")
        if saved_geometry is not None:
            self.setGeometry(
                saved_geometry.x, saved_geometry.y, saved_geometry.width, saved_geometry.height
            )
        self.setMinimumSize(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        self._colors = accent_theme_colors("cyan")
        self._dialog_provider = QtDialogProvider(self)

        # Thread-safe delivery queue -- worker threads enqueue, Qt drains
        self._delivery_queue = QtDeliveryQueue(self)
        self._timer = QtTimerDelivery(is_closing=lambda: self._is_closing, logger=LOGGER)
        self._init_services(runtime_preview_class=QtRuntimePreviewLoop)

        self._register_actions()
        self._build_layout()
        self._create_default_scene()
        self._start_autosave()
        self._key_filter = _RuntimeKeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Qt shell hooks for EditorWindowCore
    # ------------------------------------------------------------------

    def _set_window_title(self, title: str) -> None:
        self.setWindowTitle(title)

    def _after(self, delay_ms: int, callback: Callable[[], None]) -> Any:
        return self._timer.schedule(delay_ms, callback)

    def _cancel_after(self, handle: Any) -> None:
        self._timer.cancel(handle)

    def _bind_shortcuts(self) -> None:
        self._shortcut_objects: list[QShortcut] = []
        for sequence in self._shortcuts.registered_sequences():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(
                lambda key=sequence: self._shortcuts.dispatch(key, self._actions)
            )
            self._shortcut_objects.append(shortcut)

    def _preview_lighting_enabled(self) -> bool:
        return bool(self._preview_lighting_action.isChecked())

    def _apply_save_label(self, label: str) -> None:
        if hasattr(self, "_toolbar"):
            save_button = self._toolbar.action_buttons.get("save_document")
            if save_button is not None:
                save_button.setText(f"Save {label}")
        if getattr(self, "_save_action", None) is not None:
            self._save_action.setText(f"Save {label}")
            self._save_as_action.setText(f"Save {label} As...")

    def _persist_window_geometry(self) -> None:
        rect = self.geometry()
        if rect.width() > 0 and rect.height() > 0:
            geometry = WindowGeometry(rect.width(), rect.height(), rect.x(), rect.y())
            self._preferences = replace(
                self._preferences, window_geometry=geometry.to_geometry_string()
            )
            with contextlib.suppress(OSError, TypeError, ValueError):
                self._preferences_store.save(self._preferences_path, self._preferences)

    def _destroy_shell(self) -> None:
        QApplication.instance().removeEventFilter(self._key_filter)  # type: ignore[union-attr]
        QMainWindow.close(self)

    def closeEvent(self, event: Any) -> None:
        if not self._is_closing:
            self._on_close()
        event.accept()

    def run(self) -> int:
        """Show the window and run the Qt event loop."""
        self.show()
        app = QApplication.instance()
        return int(app.exec()) if app is not None else 0

    # ------------------------------------------------------------------
    # Layout (panel placement and callbacks)
    # ------------------------------------------------------------------

    def _dock(self, title: str, widget: Any, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.lower()}")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_layout(self) -> None:
        self._build_menubar()
        self._toolbar: Any = build_toolbar(
            self,
            actions=self._actions,
            contributions=self._contributions.toolbar_contributions(),
        )
        self.addToolBar(self._toolbar)

        self._viewport = ViewportPanel(
            self,
            colors=self._colors,
            on_entity_click=self._on_viewport_entity_click,
            camera_state=self._preferences.viewport_camera,
            on_camera_change=self._save_viewport_camera,
            resource_service=(
                self._engine.project.resource_service(observer=self._observer)
                if self._engine.project is not None
                else None
            ),
            observer=self._observer,
            on_transform_commit=self._push_spatial_command,
        )
        self.setCentralWidget(self._viewport)

        self._hierarchy = HierarchyPanel(
            colors=self._colors,
            actions=self._actions,
            on_select=self._on_hierarchy_select,
            on_create=self._on_hierarchy_create,
            on_add_level=self._act_add_world_level,
            on_create_connection=self._act_create_world_connection,
            on_open_level=self._open_world_level,
            on_delete=self._on_hierarchy_delete,
            on_reparent=lambda ids, target: reparent_selection_to(self, ids, target),
            on_open_source=self._act_open_instance_source,
            on_make_unique=self._act_make_instance_unique,
        )
        project_assets = (
            self._engine.project.path if self._engine.project is not None else Path.cwd() / "assets"
        )
        self._assets = AssetBrowserPanel(
            root_directory=project_assets,
            resource_root=project_assets,
            coordinator=self._coordinator,
            observer=self._observer,
            colors=self._colors,
            on_open=self._on_asset_open,
            on_drop=self._on_asset_drop,
        )
        self._inspector = InspectorPanel(
            colors=self._colors,
            on_transform_change=self._on_transform_change,
            on_rename=self._on_entity_rename,
            on_toggle_enabled=self._on_entity_toggle,
            on_script_value_change=self._on_script_value_change,
            on_add_component=self._on_add_component,
            on_component_change=lambda *args: apply_component_change(self, *args),
            on_remove_component=lambda *args: remove_component(self, *args),
            on_world_level_placement=self._on_world_level_placement,
            on_world_set_initial_level=self._on_world_set_initial_level,
            on_world_remove_item=self._on_world_remove_item,
            on_normal_map_preview=self._on_normal_map_preview,
            on_normal_map_auto_map=self._on_normal_map_auto_map,
        )
        self._console = ConsolePanel(colors=self._colors)

        self._hierarchy_dock = self._dock(
            "Hierarchy", self._hierarchy, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self._assets_dock = self._dock("Assets", self._assets, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.splitDockWidget(self._hierarchy_dock, self._assets_dock, Qt.Orientation.Vertical)
        self._inspector_dock = self._dock(
            "Inspector", self._inspector, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._console_dock = self._dock(
            "Console", self._console, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks(
            [self._hierarchy_dock, self._inspector_dock],
            [initial_hierarchy_width(_WINDOW_WIDTH), _INSPECTOR_WIDTH],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([self._console_dock], [_BOTTOM_HEIGHT], Qt.Orientation.Vertical)
        self._register_render_targets()
        self._assets.refresh()

    def _build_menubar(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        self._file_menu = file_menu
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._populate_recent_projects()
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(lambda *_a: self._on_close())

        edit_menu = menubar.addMenu("Edit")
        self._edit_menu = edit_menu
        view_menu = menubar.addMenu("View")
        self._preview_lighting_action = QAction("Preview Lighting", self)
        self._preview_lighting_action.setCheckable(True)
        self._preview_lighting_action.setChecked(True)
        self._preview_lighting_action.toggled.connect(
            lambda *_a: self._act_preview_lighting_changed()
        )
        view_menu.addAction(self._preview_lighting_action)
        menus = {"File": file_menu, "Edit": edit_menu}
        menu_actions: dict[tuple[str, str], QAction] = {}
        ordered = sorted(
            self._contributions.menu_contributions(),
            key=lambda item: (item.parent, item.group, item.order),
        )
        for contribution in ordered:
            menu = menus.get(contribution.parent)
            if menu is None:
                raise KeyError(f"Unknown menu: {contribution.parent}")
            if contribution.separator_before:
                menu.addSeparator()
            action = menu.addAction(contribution.label)
            if contribution.accelerator:
                action.setToolTip(contribution.accelerator)
            action.triggered.connect(
                lambda *_args, action_id=contribution.action_id: self._actions.dispatch(action_id)
            )
            menu_actions[(contribution.parent, contribution.label)] = action
        self._save_action = menu_actions[("File", "Save Scene")]
        self._save_as_action = menu_actions[("File", "Save Scene As...")]

    def _populate_recent_projects(self) -> None:
        self._recent_menu.clear()
        recent_projects = tuple(self._preferences.recent_projects)
        if not recent_projects:
            self._recent_menu.addAction("(none)").setEnabled(False)
            return
        for project in recent_projects:
            action = self._recent_menu.addAction(project)
            command = self._recent_project_command(project)
            action.triggered.connect(lambda *_a, c=command: c())

    def show_project_welcome(self) -> None:
        """Show a small non-blocking project manager for no-project startup."""
        welcome = QDialog(self)
        welcome.setWindowTitle("Expra Project Manager")
        layout = QVBoxLayout(welcome)
        layout.addWidget(QLabel("Start an Expra game project"))
        layout.addWidget(QLabel("Create a new project or open an existing project workspace."))
        buttons = QHBoxLayout()
        for label, command in (
            ("New Project", self._act_new_project),
            ("Open Project", self._act_open_project),
            ("Continue Scratch Scene", welcome.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda *_a, c=command: c())
            buttons.addWidget(button)
        layout.addLayout(buttons)
        welcome.setModal(False)
        welcome.show()
        self._welcome = welcome

    def _present_normal_map_preview(self, preview: Any, metadata: str) -> None:
        self._normal_map_preview = show_normal_map_preview(self, preview, metadata)

    def _open_normal_map_setup(self, plan: Any, project: Any, resources: Any) -> None:
        self._normal_map_setup = NormalMapSetupDialog(
            self, self, plan, project, resources
        )
        self._normal_map_setup.show()

    def _act_export_game(self) -> None:
        if self._engine.project is None:
            self._dialogs.show_warning("Export Game", "Open a project before exporting.")
            return
        self._export_dialog = ExportDialog(
            self,
            self._engine.project.path,
            self._coordinator,
            self._actions,
            game_version=self._engine.project.game_version,
            entry_point=self._engine.project.entry_point,
        )
        self._export_dialog.show()


__all__ = ["EditorWindow"]
