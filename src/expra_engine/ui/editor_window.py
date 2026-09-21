"""Main editor window — composition root.

Wires together:
    AppCoordinator (work)
    ButtonCoordinator (actions)
    UICoordinator (presentation)
    Engine (game state)
    Editor panels (hierarchy, viewport, inspector, console)

Threading invariant: ALL Tk mutations on the main thread.
Background work delivers results through TkDeliveryQueue → AppCoordinator
→ callback on Tk main thread.  Never call widget.after_idle() from a worker.
"""

from __future__ import annotations
import contextlib
import json
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk as tkttk
from typing import Any
import ttkbootstrap as ttk
from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.core.component import TransformComponent, registered_component_types
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.builtin_features import build_builtin_features
from expra_engine.editor.commands import (
    AddComponentCommand,
    apply_component_change,
    CommandStack,
    DeleteEntityCommand,
    RenameEntityCommand,
    SetExposedValueCommand,
    SetComponentPropertyCommand,
    RemoveComponentCommand,
    remove_component,
)
from expra_engine.editor.contributions import (
    ContributionRegistry,
    EditorContext,
    MenuFactory,
    RenderTargetRegistry,
    ShortcutRegistry,
)
from expra_engine.editor.delivery import TkDeliveryQueue
from expra_engine.editor.export_dialog import ExportDialog
from expra_engine.editor.preferences import PreferencesStore
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.editor.runtime_preview import RuntimePreviewLoop
from expra_engine.editor.script_tools import attach_script, create_behaviour_script
from expra_engine.editor.window_placement import WindowGeometry
from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry
from expra_engine.ui.asset_browser import AssetBrowserPanel
from expra_engine.ui.console import ConsolePanel
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel
from expra_engine.ui.styles import (
    STYLE_APP_FRAME,
    STYLE_PANEL_FRAME,
    accent_theme_colors,
    configure_app_styles,
)
from expra_engine.ui.timer_delivery import TimerDelivery
from expra_engine.ui.toolbar import build_toolbar
from expra_engine.ui.viewport import ViewportPanel
LOGGER = logging.getLogger(__name__)
_WINDOW_WIDTH = 1280
_WINDOW_HEIGHT = 800
_WINDOW_MIN_WIDTH = 980
_WINDOW_MIN_HEIGHT = 640
_HIERARCHY_WIDTH = 230
_HIERARCHY_MIN_WIDTH = 190
_INSPECTOR_WIDTH = 300
_INSPECTOR_MIN_WIDTH = 260
_BOTTOM_HEIGHT = 150
_BOTTOM_MIN_HEIGHT = 96
_PREFERENCES_PATH = Path.home() / ".expra" / "preferences.json"


class EditorWindow:
    """Root editor window."""

    def __init__(self, engine: Engine, *, theme: str = "bootstrap-dark") -> None:
        self._engine = engine
        self._is_closing = False
        self._pending_timer_ids: set[str] = set()
        self._sash_after_id: str | None = None
        self._autosave_after_id: str | None = None
        self._last_save_path: Path | None = None
        self._preferences_path = _PREFERENCES_PATH
        self._preferences_store = PreferencesStore()
        self._preferences = self._preferences_store.load(self._preferences_path)

        # Root window — ttkbootstrap Window replaces bare tk.Tk
        try:
            self._root = ttk.Window(themename=theme)
        except tk.TclError:
            self._root = ttk.Window(themename="darkly")
        self._root.title("Expra Editor")
        self._root.geometry(f"{_WINDOW_WIDTH}x{_WINDOW_HEIGHT}")
        saved_geometry = WindowGeometry.from_tk_geometry(self._preferences.window_geometry or "")
        if saved_geometry is not None:
            self._root.geometry(saved_geometry.to_tk_geometry())
        self._root.minsize(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.bind("<KeyPress>", self._on_runtime_key_press, add="+")
        self._root.bind("<KeyRelease>", self._on_runtime_key_release, add="+")
        self._colors = accent_theme_colors("cyan")
        self._style = tkttk.Style(self._root)
        configure_app_styles(self._style, colors=self._colors)
        self._root.configure(background=self._colors["background"])

        # Thread-safe delivery queue — worker threads enqueue, Tk drains
        self._delivery_queue = TkDeliveryQueue(self._root)

        # Coordinators
        self._coordinator = AppCoordinator(deliver=self._delivery_queue)
        self._actions = ButtonCoordinator()
        self._ui = UICoordinator()
        self._editor_context = EditorContext(
            engine=self._engine,
            actions=self._actions,
            ui=self._ui,
            app=self._coordinator,
            root=self._root,
            project=self._engine.project,
        )
        self._shortcuts = ShortcutRegistry()
        self._contributions = ContributionRegistry(
            self._actions,
            context=self._editor_context,
            shortcuts=self._shortcuts,
        )
        self._render_targets = RenderTargetRegistry()

        self._timer = TimerDelivery(
            master=self._root,
            is_closing=lambda: self._is_closing,
            pending_ids=self._pending_timer_ids,
            logger=LOGGER,
        )
        self._selected_id: str | None = None
        self._render_generations: dict[str, int] = {"inspector": 0}
        self._render_owners: dict[str, str | None] = {"inspector": None}
        self._command_stack: CommandStack = CommandStack()
        self._project_workflow = ProjectWorkflow(self)
        self._runtime_preview = RuntimePreviewLoop(
            self._root,
            self._engine,
            lambda: self._request_render(
                "viewport", (self._engine.active_scene, None), priority=20
            ),
        )

        self._register_actions()
        self._build_layout()
        self._create_default_scene()
        self._start_autosave()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _on_runtime_key_press(self, event: Any) -> None:
        self._forward_runtime_key("press", getattr(event, "keysym", ""))

    def _on_runtime_key_release(self, event: Any) -> None:
        self._forward_runtime_key("release", getattr(event, "keysym", ""))

    def _forward_runtime_key(self, phase: str, key: object) -> None:
        if self._engine.run_state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return
        control = str(key).lower()
        if not control:
            return
        transitions = getattr(self._engine.input_map, phase)(PhysicalInput("keyboard", control))
        for action_event in transitions:
            self._engine.signal(action_event)

    def _build_layout(self) -> None:
        self._build_menubar()
        main = ttk.Frame(self._root, style=STYLE_APP_FRAME)
        main.pack(fill="both", expand=True)

        # Toolbar at top
        self._toolbar = build_toolbar(
            main,
            actions=self._actions,
            contributions=self._contributions.toolbar_contributions(),
        )

        # Center and console are independently resizable; the viewport gets the
        # flexible weight while side panes retain usable minimum widths.
        self._main_paned = ttk.Panedwindow(main, orient="vertical")
        self._main_paned.pack(fill="both", expand=True, pady=(2, 0))
        center = ttk.Frame(self._main_paned, style=STYLE_APP_FRAME)
        self._main_paned.add(center, weight=1)
        self._console_host = ttk.Frame(self._main_paned, style=STYLE_PANEL_FRAME)
        self._main_paned.add(self._console_host, weight=0)
        self._main_paned.bind("<Configure>", self._clamp_vertical_sash, add="+")

        self._content_paned = ttk.Panedwindow(center, orient="horizontal")
        self._content_paned.pack(fill="both", expand=True)

        # Left pane: hierarchy and project assets
        hier_frame = ttk.Frame(self._content_paned, width=_HIERARCHY_WIDTH, style=STYLE_PANEL_FRAME)
        left_paned = ttk.Panedwindow(hier_frame, orient="vertical")
        left_paned.pack(fill="both", expand=True)
        hierarchy_host = ttk.Frame(left_paned, style=STYLE_PANEL_FRAME)
        assets_host = ttk.Frame(left_paned, style=STYLE_PANEL_FRAME)
        left_paned.add(hierarchy_host, weight=3)
        left_paned.add(assets_host, weight=2)
        self._hierarchy = HierarchyPanel(
            hierarchy_host,
            colors=self._colors,
            actions=self._actions,
            on_select=self._on_hierarchy_select,
            on_create=self._on_hierarchy_create,
            on_delete=self._on_hierarchy_delete,
        )
        self._hierarchy.pack(fill="both", expand=True)
        project_assets = (
            self._engine.project.assets_dir
            if self._engine.project is not None
            else Path.cwd() / "assets"
        )
        self._assets = AssetBrowserPanel(
            assets_host,
            root_directory=project_assets,
            resource_root=project_assets,
            coordinator=self._coordinator,
            colors=self._colors,
            on_open=self._on_asset_open,
        )
        self._assets.pack(fill="both", expand=True)
        self._hierarchy_host = hierarchy_host
        self._assets_host = assets_host
        self._left_paned = left_paned
        self._content_paned.add(hier_frame, weight=0)

        # Center pane: viewport
        view_frame = ttk.Frame(self._content_paned, style=STYLE_APP_FRAME)
        self._viewport = ViewportPanel(
            view_frame,
            on_entity_click=self._on_viewport_entity_click,
            camera_state=self._preferences.viewport_camera,
            on_camera_change=self._save_viewport_camera,
        )
        self._viewport.pack(fill="both", expand=True)
        self._viewport_host = view_frame
        self._content_paned.add(view_frame, weight=1)

        # Right pane: inspector
        insp_frame = ttk.Frame(
            self._content_paned,
            width=_INSPECTOR_WIDTH,
            style=STYLE_PANEL_FRAME,
        )
        self._inspector = InspectorPanel(
            insp_frame,
            colors=self._colors,
            on_transform_change=self._on_transform_change,
            on_rename=self._on_entity_rename,
            on_toggle_enabled=self._on_entity_toggle,
            on_script_value_change=self._on_script_value_change,
            on_add_component=self._on_add_component,
            on_component_change=lambda *args: apply_component_change(self, *args),
            on_remove_component=lambda *args: remove_component(self, *args),
        )
        self._inspector.pack(fill="both", expand=True)
        self._inspector_host = insp_frame
        self._content_paned.add(insp_frame, weight=0)
        self._content_paned.bind("<Configure>", self._clamp_horizontal_sashes, add="+")

        # Bottom: console (fixed height)
        self._console = ConsolePanel(self._console_host, colors=self._colors)
        self._console.pack(fill="both", expand=True)
        self._register_render_targets()
        self._sash_after_id = self._root.after_idle(self._set_initial_sashes)
        self._assets.refresh()

    def _on_asset_open(self, entry: Any) -> None:
        if entry.logical_id is not None:
            self._console.log(f"[Assets] Open: {entry.logical_id}", level="info")

    def _set_initial_sashes(self) -> None:
        """Place side panes after Tk has measured the initial shell."""
        self._sash_after_id = None
        try:
            width = self._content_paned.winfo_width()
            height = self._main_paned.winfo_height()
            if width <= 1 or height <= 1:
                self._sash_after_id = self._root.after(25, self._set_initial_sashes)
                return

            self._content_paned.sashpos(0, _HIERARCHY_WIDTH)
            self._content_paned.sashpos(1, max(_HIERARCHY_WIDTH + 260, width - _INSPECTOR_WIDTH))
            self._main_paned.sashpos(0, max(300, height - _BOTTOM_HEIGHT))
            self._clamp_horizontal_sashes()
            self._clamp_vertical_sash()
        except tk.TclError:
            return

    def show_project_welcome(self) -> None:
        """Show a small non-blocking project manager for no-project startup."""
        welcome = tk.Toplevel(self._root)
        welcome.title("Expra Project Manager")
        welcome.transient(self._root)
        welcome.resizable(False, False)
        tk.Label(
            welcome,
            text="Start an Expra game project",
            padx=24,
            pady=16,
        ).pack()
        tk.Label(
            welcome,
            text="Create a new project or open an existing project workspace.",
            padx=24,
            pady=12,
        ).pack()
        buttons = tk.Frame(welcome)
        buttons.pack(padx=18, pady=(0, 18), fill="x")
        tk.Button(buttons, text="New Project", command=self._act_new_project).pack(
            side="left", padx=4
        )
        tk.Button(buttons, text="Open Project", command=self._act_open_project).pack(
            side="left", padx=4
        )
        tk.Button(buttons, text="Continue Scratch Scene", command=welcome.destroy).pack(
            side="left", padx=4
        )

    def _clamp_horizontal_sashes(self, _event: Any = None) -> None:
        try:
            width = self._content_paned.winfo_width()
            if width <= 1:
                return
            max_first = width - _INSPECTOR_MIN_WIDTH - 260
            if max_first < _HIERARCHY_MIN_WIDTH:
                return
            first = min(max(_HIERARCHY_MIN_WIDTH, self._content_paned.sashpos(0)), max_first)
            second = min(
                max(first + 260, self._content_paned.sashpos(1)), width - _INSPECTOR_MIN_WIDTH
            )
            self._content_paned.sashpos(0, first)
            self._content_paned.sashpos(1, second)
        except tk.TclError:
            return

    def _clamp_vertical_sash(self, _event: Any = None) -> None:
        try:
            height = self._main_paned.winfo_height()
            if height > 1:
                position = min(max(300, self._main_paned.sashpos(0)), height - _BOTTOM_MIN_HEIGHT)
                self._main_paned.sashpos(0, position)
        except tk.TclError:
            return

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self._root)
        self._root.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        self._recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self._recent_menu)
        self._populate_recent_projects()
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self._edit_menu = edit_menu
        MenuFactory({"File": file_menu, "Edit": edit_menu}).build(
            self._contributions.menu_contributions(),
            self._actions,
        )

    def _register_render_targets(self) -> None:
        self._render_targets.register("hierarchy", self._render_hierarchy)
        self._render_targets.register("inspector", self._render_inspector)
        self._render_targets.register("viewport", self._render_viewport)
        self._render_targets.register("toolbar", self._render_toolbar)

    def _render_hierarchy(self, intent: RenderIntent) -> None:
        self._hierarchy.render(intent.payload)

    def _render_inspector(self, intent: RenderIntent) -> None:
        self._inspector.render(intent.payload)

    def _render_toolbar(self, _intent: RenderIntent) -> None:
        self._update_play_pause_state()

    def _act_export_game(self) -> None:
        if self._engine.project is None:
            messagebox.showwarning("Export Game", "Open a project before exporting.")
            return
        ExportDialog(
            self._root,
            self._engine.project.path,
            self._coordinator,
            self._actions,
            game_version=self._engine.project.game_version,
            entry_point=self._engine.project.entry_point,
        )

    def _act_undo(self) -> None:
        cmd = self._command_stack.undo()
        if cmd is not None:
            self._console.log(f"[Edit] Undo: {cmd.description}")
            self._present_all()
        self._update_undo_redo_state()

    def _act_redo(self) -> None:
        cmd = self._command_stack.redo()
        if cmd is not None:
            self._console.log(f"[Edit] Redo: {cmd.description}")
            self._present_all()
        self._update_undo_redo_state()

    def _update_undo_redo_state(self) -> None:
        self._actions.set_enabled("undo", self._command_stack.can_undo)
        self._actions.set_enabled("redo", self._command_stack.can_redo)

    def _register_actions(self) -> None:
        for feature in build_builtin_features(self):
            self._contributions.register(feature)
        self._shortcuts.bind(self._root, self._actions)
        self._update_play_pause_state()

    # Engine actions
    # ------------------------------------------------------------------

    def _act_play(self) -> None:
        if self._engine.play():
            self._console.log("[Engine] Play", level="info")
            self._runtime_preview.start()
        self._update_play_pause_state()
        self._present_all()

    def _act_pause(self) -> None:
        if self._engine.pause():
            self._console.log("[Engine] Paused", level="info")
        self._update_play_pause_state()
        self._present_all()

    def _act_stop(self) -> None:
        self._runtime_preview.stop()
        if self._engine.stop():
            self._console.log("[Engine] Stopped — scene restored", level="info")
        self._update_play_pause_state()
        self._present_all()
    # ------------------------------------------------------------------
    # Project and scene actions
    # ------------------------------------------------------------------

    def _act_new_scene(self) -> None:
        project = self._engine.project
        if project is not None:
            name = simpledialog.askstring("New Scene", "Scene name:", parent=self._root)
            if not name:
                return
            relative = f"scenes/{Path(name).stem}.json"
            scene = Scene(name)
            project.register_scene_path(relative)
            self._last_save_path = project.path / relative
        else:
            scene = Scene("New Scene")
        self._engine.set_scene(scene)
        self._selected_id = None
        self._actions.set_enabled("delete_entity", False)
        self._console.log(f"[Editor] Created scene: {scene.name}")
        self._present_all()

    def _act_new_project(self) -> None:
        self._project_workflow.new_project()

    def _act_open_project(self) -> None:
        self._project_workflow.open_project()

    def _act_open_project_manifest(self) -> None:
        self._project_workflow.open_project_manifest()

    def _act_import_asset(self) -> None:
        self._project_workflow.import_assets()

    def _act_configure_input(self) -> None:
        self._project_workflow.configure_input()

    def _act_close_project(self) -> None:
        self._project_workflow.close_project()

    def _open_loaded_project(self, project: Project) -> None:
        self._project_workflow.open_loaded(project)

    def _act_save_scene(self) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            messagebox.showwarning("Save Scene", "No scene to save.")
            return
        project = self._engine.project
        if project is not None and self._last_save_path is not None:
            relative = self._last_save_path.resolve().relative_to(project.path)
            project.save_scene(scene, relative.as_posix())
            self._console.log(f"[Editor] Scene saved: {self._last_save_path}")
            return
        path = filedialog.asksaveasfilename(
            title="Save Scene",
            defaultextension=".json",
            filetypes=[("Scene files", "*.json")],
        )
        if not path:
            return
        self._last_save_path = Path(path)
        self._act_save_scene_silent()
        self._console.log(f"[Editor] Scene saved: {path}")

    def _act_save_scene_silent(self) -> None:
        """Save to the last selected path without opening a dialog."""
        if self._last_save_path is None:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        self._last_save_path.write_text(json.dumps(scene.to_dict(), indent=2), encoding="utf-8")

    def _start_autosave(self) -> None:
        """Schedule recurring silent saves using the configured preference."""
        interval_ms = max(1, int(self._preferences.autosave_interval_ms))

        def autosave() -> None:
            self._autosave_after_id = None
            self._act_save_scene_silent()
            if not self._is_closing:
                self._autosave_after_id = self._root.after(interval_ms, autosave)

        if self._autosave_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._root.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self._root.after(interval_ms, autosave)

    def _populate_recent_projects(self) -> None:
        self._recent_menu.delete(0, "end")
        recent_projects = tuple(self._preferences.recent_projects)
        if not recent_projects:
            self._recent_menu.add_command(label="(none)", state="disabled")
            return
        for project in recent_projects:
            self._recent_menu.add_command(
                label=project,
                command=self._recent_project_command(project),
            )

    def _recent_project_command(self, project: str) -> Callable[[], None]:
        return lambda: self._act_open_recent(project)

    def _act_open_recent(self, project: str) -> None:
        self._project_workflow.open_recent(project)

    def _act_add_entity(self) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        self._on_hierarchy_create()

    def _act_delete_entity(self) -> None:
        if self._engine.run_state == EngineRunState.EDIT and self._selected_id:
            self._on_hierarchy_delete(self._selected_id)

    # ------------------------------------------------------------------
    # Scripting actions
    # ------------------------------------------------------------------

    def _act_new_script(self) -> None:
        project = self._engine.project
        if project is None:
            messagebox.showwarning("New Script", "Open a project before creating scripts.")
            return
        relative_path = simpledialog.askstring(
            "New Script", "Path under scripts/", parent=self._root
        )
        class_name = simpledialog.askstring("New Script", "Behaviour class name", parent=self._root)
        if not relative_path or not class_name:
            return
        try:
            resource = create_behaviour_script(project.path, f"scripts/{relative_path}", class_name)
        except (ValueError, FileExistsError) as exc:
            messagebox.showerror("New Script", str(exc), parent=self._root)
            return
        self._console.log(f"[Editor] Created script: {resource}")
        self._assets.refresh()

    def _act_attach_script(self) -> None:
        if self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        if entity is None:
            return
        script_id = simpledialog.askstring(
            "Attach Script", "project://scripts/example.py", parent=self._root
        )
        class_name = simpledialog.askstring(
            "Attach Script", "Behaviour class name", parent=self._root
        )
        if not script_id or not class_name:
            return
        try:
            component = attach_script(entity, script_id, class_name)
            with contextlib.suppress(OSError, ImportError, AttributeError, TypeError, ValueError):
                project_root = self._engine.project.path if self._engine.project else Path.cwd()
                behaviour_type = ScriptRegistry(project_root).resolve(script_id, class_name)
                component.exposed_values = {
                    name: field.default for name, field in behaviour_type.exposed_schema().items()
                }
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Attach Script", str(exc), parent=self._root)
            return
        self._console.log(f"[Editor] Attached {class_name} to {entity.name}")
        self._on_hierarchy_select(entity.entity_id)
        self._present_all()

    def _act_remove_script(self) -> None:
        if self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        if entity is None:
            return
        scripts = [
            component for component in entity.components if isinstance(component, ScriptComponent)
        ]
        if scripts:
            entity.remove_component(scripts[-1])
            self._console.log(f"[Editor] Removed script from {entity.name}")
            self._on_hierarchy_select(entity.entity_id)
            self._present_all()

    def _on_hierarchy_select(self, entity_id: str | None) -> None:
        self._selected_id = entity_id
        self._actions.set_enabled("delete_entity", entity_id is not None)
        scene = self._engine.active_scene
        entity = scene.find_entity(entity_id) if scene and entity_id else None
        has_script = bool(
            entity is not None
            and any(isinstance(component, ScriptComponent) for component in entity.components)
        )
        self._actions.set_enabled("attach_script", entity_id is not None and not has_script)
        self._actions.set_enabled("remove_script", has_script)
        self._present_selection(scene, entity)

    def _on_add_component(self, component_name: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT or self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        component_type = dict(registered_component_types()).get(component_name)
        if entity is None or component_type is None:
            return
        if any(isinstance(component, component_type) for component in entity.components):
            return
        try:
            self._command_stack.push(AddComponentCommand(scene, entity.entity_id, component_type))
        except TypeError as exc:
            messagebox.showerror("Add Component", str(exc), parent=self._root)
            return
        self._console.log(f"[Editor] Added {component_name} to {entity.name}")
        self._present_all()

    # ------------------------------------------------------------------
    # Hierarchy callbacks
    # ------------------------------------------------------------------

    def _on_hierarchy_create(self) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            scene = Scene("New Scene")
            self._engine.set_scene(scene)
        entity = scene.create_entity("Entity")
        entity.add_component(TransformComponent())
        self._console.log(f"[Editor] Created entity: {entity.name}")
        self._present_all()
        self._hierarchy.select(entity.entity_id)
        self._on_hierarchy_select(entity.entity_id)
    def _on_hierarchy_delete(self, entity_id: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        cmd = DeleteEntityCommand(scene, entity)
        self._command_stack.push(cmd)
        self._console.log(f"[Editor] Deleted entity: {entity.name}")
        if self._selected_id == entity_id:
            self._selected_id = None
            self._actions.set_enabled("delete_entity", False)
        self._update_undo_redo_state()
        self._present_all()
    def _on_transform_change(self, entity_id: str, field: str, value: float) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        transform = entity.get_component(TransformComponent)
        if transform is None:
            return
        setattr(transform, field, value)
        self._request_render("viewport", (scene, self._selected_id), priority=10)

    def _on_entity_rename(self, entity_id: str, new_name: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        cmd = RenameEntityCommand(entity, entity.name, new_name)
        self._command_stack.push(cmd)
        self._update_undo_redo_state()
        self._ui.begin_batch()
        self._request_render("hierarchy", scene, priority=20)
        self._request_render("viewport", (scene, self._selected_id), priority=10)
        self._ui.end_batch()
        self._hierarchy.select(entity_id)

    def _on_entity_toggle(self, entity_id: str, enabled: bool) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        entity.enabled = enabled
        self._present_all()

    # ------------------------------------------------------------------
    # Inspector callbacks
    # ------------------------------------------------------------------

    def _on_script_value_change(
        self, entity_id: str, component_index: int, field: str, value: Any
    ) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None or scene.find_entity(entity_id) is None:
            return
        self._command_stack.push(
            SetExposedValueCommand(scene, entity_id, component_index, field, value)
        )
        self._update_undo_redo_state()
        self._present_all()

    def _on_viewport_entity_click(self, entity_id: str | None) -> None:
        self._on_hierarchy_select(entity_id)
        self._hierarchy.select(entity_id)

    def _save_viewport_camera(self, values: dict[str, object]) -> None:
        self._preferences = replace(self._preferences, viewport_camera=values)
        self._preferences_store.save(self._preferences_path, self._preferences)
    # Refresh helpers

    def _refresh_viewport(self) -> None:
        self._request_render(
            "viewport",
            (self._engine.active_scene, self._selected_id),
            priority=10,
        )

    def _refresh_all(self) -> None:
        self._present_all()

    def _update_play_pause_state(self) -> None:
        state = self._engine.run_state
        self._actions.set_enabled("play", state != EngineRunState.PLAY)
        self._actions.set_enabled("pause", state == EngineRunState.PLAY)
        self._actions.set_enabled("stop", state != EngineRunState.EDIT)
        self._actions.set_enabled("add_entity", state == EngineRunState.EDIT)
        self._actions.set_enabled(
            "delete_entity", state == EngineRunState.EDIT and self._selected_id is not None
        )
        self._update_project_actions()

    def _update_project_actions(self) -> None:
        has_project = self._engine.project is not None
        self._actions.set_enabled("save_scene", has_project)
        self._actions.set_enabled("close_project", has_project)
        self._actions.set_enabled("new_script", has_project)
        self._actions.set_enabled("import_asset", has_project)
        self._actions.set_enabled("configure_input", has_project)
        self._actions.set_enabled("editor.export_game", has_project)

    def _create_default_scene(self) -> None:
        scene = Scene("Sample Scene")
        entity = scene.create_entity("Camera")
        entity.add_component(TransformComponent(x=0, y=0))
        entity2 = scene.create_entity("Player")
        entity2.add_component(TransformComponent(x=80, y=-40))
        self._engine.set_scene(scene)
        self._console.log("[Editor] Expra Engine started")
        self._console.log(f"[Editor] Loaded scene: {scene.name}")
        self._present_all()

    # ------------------------------------------------------------------
    # Coordinated presentation and lifecycle
    # ------------------------------------------------------------------

    def _request_render(
        self,
        target: str,
        payload: object,
        *,
        owner_id: str | None = None,
        priority: int = 0,
    ) -> None:
        if target == "inspector":
            previous = self._render_owners["inspector"]
            if owner_id is None and previous is not None:
                self._render_generations["inspector"] += 1
                self._ui.clear("inspector")
                self._render_owners["inspector"] = None
            elif owner_id != previous:
                self._render_generations["inspector"] += 1
                self._render_owners["inspector"] = owner_id
                self._ui.invalidate(
                    "inspector",
                    generation=self._render_generations["inspector"],
                    owner_id=owner_id,
                )
            generation = self._render_generations["inspector"]
        else:
            generation = 0
        intent = RenderIntent(
            target=target,
            generation=generation,
            owner_id=owner_id,
            payload=payload,
            payload_set=True,
            priority=priority,
        )
        self._ui.request(intent, self._render_targets.callback_for(target))

    def _render_viewport(self, intent: RenderIntent) -> None:
        payload = intent.payload
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        scene, selected_id = payload
        runtime_preview = self._engine.run_state in (EngineRunState.PLAY, EngineRunState.PAUSED)
        self._viewport.render(
            scene,
            selected_id,
            editor_overlays=not runtime_preview,
            interpolator=self._engine.transform_interpolator if runtime_preview else None,
            interpolation_fraction=self._engine.interpolation_fraction if runtime_preview else 0.0,
            animated_players=self._engine.animated_sprite_system.players,
        )

    def _present_selection(self, scene: Scene | None, entity: Any) -> None:
        self._ui.begin_batch()
        self._request_render("hierarchy", scene, priority=20)
        self._request_render("inspector", entity, owner_id=self._selected_id, priority=30)
        self._request_render("viewport", (scene, self._selected_id), priority=10)
        self._ui.end_batch()

    def _present_all(self) -> None:
        scene = self._engine.active_scene
        entity = scene.find_entity(self._selected_id) if scene and self._selected_id else None
        self._ui.begin_batch()
        self._request_render("hierarchy", scene, priority=20)
        self._request_render("inspector", entity, owner_id=self._selected_id, priority=30)
        self._request_render("viewport", (scene, self._selected_id), priority=10)
        self._request_render("toolbar", self._engine.run_state, priority=40)
        self._ui.end_batch()

    def _on_close(self) -> None:
        self._runtime_preview.stop()
        self._is_closing = True
        if self._autosave_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._root.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        geometry = WindowGeometry.from_tk_geometry(self._root.geometry())
        if geometry is not None:
            self._preferences = replace(
                self._preferences,
                window_geometry=geometry.to_tk_geometry(),
            )
            with contextlib.suppress(OSError, TypeError, ValueError):
                self._preferences_store.save(self._preferences_path, self._preferences)
        if self._sash_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._root.after_cancel(self._sash_after_id)
            self._sash_after_id = None
        self._timer.cancel_all()
        self._contributions.stop_all()
        self._delivery_queue.close()
        self._coordinator.shutdown()
        self._ui.shutdown()
        self._root.destroy()

    def run(self) -> None:
        """Start the Tk main loop."""
        self._root.mainloop()
