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
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk as tkttk
from typing import Any

import ttkbootstrap as ttk

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import CommandStack, DeleteEntityCommand, RenameEntityCommand
from expra_engine.editor.delivery import TkDeliveryQueue
from expra_engine.editor.export_dialog import ExportDialog
from expra_engine.editor.preferences import PreferencesStore
from expra_engine.editor.window_placement import WindowGeometry
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

        self._register_actions()
        self._build_layout()
        self._create_default_scene()
        self._start_autosave()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        self._build_menubar()
        main = ttk.Frame(self._root, style=STYLE_APP_FRAME)
        main.pack(fill="both", expand=True)

        # Toolbar at top
        self._toolbar = build_toolbar(main, actions=self._actions)

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

        # Left pane: hierarchy
        hier_frame = ttk.Frame(self._content_paned, width=_HIERARCHY_WIDTH, style=STYLE_PANEL_FRAME)
        self._hierarchy = HierarchyPanel(
            hier_frame,
            colors=self._colors,
            actions=self._actions,
            on_select=self._on_hierarchy_select,
            on_create=self._on_hierarchy_create,
            on_delete=self._on_hierarchy_delete,
        )
        self._hierarchy.pack(fill="both", expand=True)
        self._hierarchy_host = hier_frame
        self._content_paned.add(hier_frame, weight=0)

        # Center pane: viewport
        view_frame = ttk.Frame(self._content_paned, style=STYLE_APP_FRAME)
        self._viewport = ViewportPanel(
            view_frame,
            on_entity_click=self._on_viewport_entity_click,
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
        )
        self._inspector.pack(fill="both", expand=True)
        self._inspector_host = insp_frame
        self._content_paned.add(insp_frame, weight=0)
        self._content_paned.bind("<Configure>", self._clamp_horizontal_sashes, add="+")

        # Bottom: console (fixed height)
        self._console = ConsolePanel(self._console_host, colors=self._colors)
        self._console.pack(fill="both", expand=True)
        self._sash_after_id = self._root.after_idle(self._set_initial_sashes)

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
        file_menu.add_command(
            label="New Scene", command=lambda: self._actions.dispatch("new_scene"), accelerator=""
        )
        file_menu.add_command(
            label="Save Scene...",
            command=lambda: self._actions.dispatch("save_scene"),
            accelerator="",
        )
        self._recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self._recent_menu)
        self._populate_recent_projects()
        file_menu.add_separator()
        file_menu.add_command(
            label="Export Game...", command=lambda: self._actions.dispatch("editor.export_game")
        )
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(
            label="Undo", command=lambda: self._actions.dispatch("undo"), accelerator="Ctrl+Z"
        )
        edit_menu.add_command(
            label="Redo", command=lambda: self._actions.dispatch("redo"), accelerator="Ctrl+Y"
        )
        self._edit_menu = edit_menu

    def _act_export_game(self) -> None:
        ExportDialog(
            self._root,
            Path(".").resolve(),
            self._coordinator,
            self._actions,
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

    # ------------------------------------------------------------------
    # Action registration
    # ------------------------------------------------------------------

    def _register_actions(self) -> None:
        a = self._actions
        a.register("play", self._act_play)
        a.register("pause", self._act_pause)
        a.register("stop", self._act_stop)
        a.register("new_scene", self._act_new_scene)
        a.register("save_scene", self._act_save_scene)
        a.register("add_entity", self._act_add_entity)
        a.register("delete_entity", self._act_delete_entity, enabled=False)
        a.register("editor.export_game", self._act_export_game)
        a.register("undo", self._act_undo, enabled=False)
        a.register("redo", self._act_redo, enabled=False)
        self._root.bind_all("<Control-z>", lambda _e: self._actions.dispatch("undo"))
        self._root.bind_all("<Control-y>", lambda _e: self._actions.dispatch("redo"))
        self._update_play_pause_state()

    # ------------------------------------------------------------------
    # Engine actions
    # ------------------------------------------------------------------

    def _act_play(self) -> None:
        if self._engine.play():
            self._console.log("[Engine] Play", level="info")
        self._update_play_pause_state()
        self._present_all()

    def _act_pause(self) -> None:
        if self._engine.pause():
            self._console.log("[Engine] Paused", level="info")
        self._update_play_pause_state()
        self._present_all()

    def _act_stop(self) -> None:
        if self._engine.stop():
            self._console.log("[Engine] Stopped — scene restored", level="info")
        self._update_play_pause_state()
        self._present_all()

    def _act_new_scene(self) -> None:
        scene = Scene("New Scene")
        self._engine.set_scene(scene)
        self._selected_id = None
        self._actions.set_enabled("delete_entity", False)
        self._console.log(f"[Editor] Created scene: {scene.name}")
        self._present_all()

    def _act_save_scene(self) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            messagebox.showwarning("Save Scene", "No scene to save.")
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
                command=lambda path=project: self._act_open_recent(path),
            )

    def _act_open_recent(self, project: str) -> None:
        self._console.log(f"[Editor] Recent project selected: {project}")

    def _act_add_entity(self) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        self._on_hierarchy_create()

    def _act_delete_entity(self) -> None:
        if self._engine.run_state == EngineRunState.EDIT and self._selected_id:
            self._on_hierarchy_delete(self._selected_id)

    # ------------------------------------------------------------------
    # Hierarchy callbacks
    # ------------------------------------------------------------------

    def _on_hierarchy_select(self, entity_id: str | None) -> None:
        self._selected_id = entity_id
        self._actions.set_enabled("delete_entity", entity_id is not None)
        scene = self._engine.active_scene
        entity = scene.find_entity(entity_id) if scene and entity_id else None
        self._present_selection(scene, entity)

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

    # ------------------------------------------------------------------
    # Inspector callbacks
    # ------------------------------------------------------------------

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
    # Viewport callbacks
    # ------------------------------------------------------------------

    def _on_viewport_entity_click(self, entity_id: str) -> None:
        self._on_hierarchy_select(entity_id)
        self._hierarchy.select(entity_id)

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Default scene
    # ------------------------------------------------------------------

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
    # Coordinated presentation
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
        self._ui.request(intent, self._apply_render)

    def _apply_render(self, intent: RenderIntent) -> None:
        if intent.target == "hierarchy":
            self._hierarchy.render(intent.payload)
        elif intent.target == "inspector":
            self._inspector.render(intent.payload)
        elif intent.target == "viewport":
            payload = intent.payload
            if not isinstance(payload, tuple) or len(payload) != 2:
                return
            scene, selected_id = payload
            self._viewport.render(scene, selected_id)
        elif intent.target == "toolbar":
            self._update_play_pause_state()

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
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
        self._delivery_queue.close()
        self._coordinator.shutdown()
        self._ui.shutdown()
        self._root.destroy()

    def run(self) -> None:
        """Start the Tk main loop."""
        self._root.mainloop()
