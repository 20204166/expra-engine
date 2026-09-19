"""Main editor window — composition root.

Wires together:
    AppCoordinator (work)
    ButtonCoordinator (actions)
    UICoordinator (presentation)
    Engine (game state)
    Editor panels (hierarchy, viewport, inspector, assets, console)

Flow:
    user action -> ButtonCoordinator -> engine mutation
        -> UICoordinator -> panel.render() -> Tk presentation

Threading invariant: ALL Tk mutations on the main thread.
Background work delivers results through AppCoordinator -> deliver -> main thread.
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.coordinators.ui_coordinator import UICoordinator
from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.ui.console import ConsolePanel
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel
from expra_engine.ui.styles import COLORS, configure_app_styles
from expra_engine.ui.timer_delivery import TimerDelivery
from expra_engine.ui.toolbar import build_toolbar
from expra_engine.ui.viewport import ViewportPanel

LOGGER = logging.getLogger(__name__)
_WINDOW_WIDTH = 1280
_WINDOW_HEIGHT = 800
_HIERARCHY_WIDTH = 240
_INSPECTOR_WIDTH = 280
_BOTTOM_HEIGHT = 160


class EditorWindow:
    """Root editor window."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._is_closing = False
        self._pending_timer_ids: set[str] = set()

        # Root window
        self._root = tk.Tk()
        self._root.title("Expra Editor")
        self._root.geometry(f"{_WINDOW_WIDTH}x{_WINDOW_HEIGHT}")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        configure_app_styles(style)

        # Delivery: schedule callbacks on Tk main thread
        def deliver(callback: Any) -> None:
            with contextlib.suppress(RuntimeError, tk.TclError):
                self._root.after_idle(callback)

        # Coordinators
        self._coordinator = AppCoordinator(deliver=deliver)
        self._actions = ButtonCoordinator()
        self._ui = UICoordinator()

        self._timer = TimerDelivery(
            master=self._root,
            is_closing=lambda: self._is_closing,
            pending_ids=self._pending_timer_ids,
            logger=LOGGER,
        )

        # Build layout
        self._build_layout()
        self._register_actions()
        self._create_default_scene()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        c = COLORS
        main = tk.Frame(self._root, bg=c["background"])
        main.pack(fill="both", expand=True)

        # Toolbar at top
        self._toolbar = build_toolbar(main, actions=self._actions, colors=c)

        # Content area: hierarchy | viewport | inspector
        content = tk.Frame(main, bg=c["background"])
        content.pack(fill="both", expand=True)

        # Hierarchy (left)
        self._hierarchy = HierarchyPanel(
            content,
            colors=c,
            on_select=self._on_hierarchy_select,
            on_create=self._on_hierarchy_create,
            on_delete=self._on_hierarchy_delete,
        )
        self._hierarchy.pack(side="left", fill="y", padx=(0, 2))
        self._hierarchy.configure(width=_HIERARCHY_WIDTH)
        self._hierarchy.pack_propagate(False)

        # Inspector (right)
        self._inspector = InspectorPanel(
            content,
            colors=c,
            on_transform_change=self._on_transform_change,
            on_rename=self._on_entity_rename,
            on_toggle_enabled=self._on_entity_toggle,
        )
        self._inspector.pack(side="right", fill="y", padx=(2, 0))
        self._inspector.configure(width=_INSPECTOR_WIDTH)
        self._inspector.pack_propagate(False)

        # Viewport (center)
        self._viewport = ViewportPanel(
            content,
            colors=c,
            on_entity_click=self._on_viewport_entity_click,
        )
        self._viewport.pack(fill="both", expand=True)

        # Bottom: console
        self._console = ConsolePanel(self._root, colors=c)
        self._console.pack(fill="x", side="bottom")
        self._console.configure(height=_BOTTOM_HEIGHT)
        self._console.pack_propagate(False)

        self._selected_id: str | None = None

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

        self._update_play_pause_state()

    # ------------------------------------------------------------------
    # Engine actions (called from ButtonCoordinator)
    # ------------------------------------------------------------------

    def _act_play(self) -> None:
        changed = self._engine.play()
        if changed:
            self._console.log("[Engine] Play", level="info")
        self._update_play_pause_state()
        self._refresh_viewport()

    def _act_pause(self) -> None:
        changed = self._engine.pause()
        if changed:
            self._console.log("[Engine] Paused", level="info")
        self._update_play_pause_state()

    def _act_stop(self) -> None:
        changed = self._engine.stop()
        if changed:
            self._console.log("[Engine] Stopped — scene restored", level="info")
        self._update_play_pause_state()
        self._refresh_all()

    def _act_new_scene(self) -> None:
        scene = Scene("New Scene")
        self._engine.set_scene(scene)
        self._selected_id = None
        self._console.log(f"[Editor] Created scene: {scene.name}")
        self._refresh_all()

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
        import json
        Path(path).write_text(json.dumps(scene.to_dict(), indent=2), encoding="utf-8")
        self._console.log(f"[Editor] Scene saved: {path}")

    def _act_add_entity(self) -> None:
        self._on_hierarchy_create()

    def _act_delete_entity(self) -> None:
        if self._selected_id:
            self._on_hierarchy_delete(self._selected_id)

    # ------------------------------------------------------------------
    # Hierarchy callbacks
    # ------------------------------------------------------------------

    def _on_hierarchy_select(self, entity_id: str | None) -> None:
        self._selected_id = entity_id
        self._actions.set_enabled("delete_entity", entity_id is not None)
        scene = self._engine.active_scene
        entity = scene.find_entity(entity_id) if scene and entity_id else None
        self._inspector.render(entity)
        self._refresh_viewport()

    def _on_hierarchy_create(self) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            scene = Scene("New Scene")
            self._engine.set_scene(scene)
        entity = scene.create_entity("Entity")
        entity.add_component(TransformComponent())
        self._console.log(f"[Editor] Created entity: {entity.name}")
        self._refresh_all()
        self._hierarchy.select(entity.entity_id)
        self._on_hierarchy_select(entity.entity_id)

    def _on_hierarchy_delete(self, entity_id: str) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        removed = scene.remove_entity(entity_id)
        if removed:
            self._console.log(f"[Editor] Deleted entity: {entity.name}")
            if self._selected_id == entity_id:
                self._selected_id = None
                self._inspector.render(None)
        self._refresh_all()

    # ------------------------------------------------------------------
    # Inspector callbacks
    # ------------------------------------------------------------------

    def _on_transform_change(self, entity_id: str, field: str, value: float) -> None:
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
        self._refresh_viewport()

    def _on_entity_rename(self, entity_id: str, new_name: str) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        entity.name = new_name
        self._hierarchy.render(scene)
        self._hierarchy.select(entity_id)

    def _on_entity_toggle(self, entity_id: str, enabled: bool) -> None:
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        entity.enabled = enabled
        self._refresh_all()

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
        self._viewport.render(self._engine.active_scene, self._selected_id)

    def _refresh_all(self) -> None:
        scene = self._engine.active_scene
        self._hierarchy.render(scene)
        self._refresh_viewport()

    def _update_play_pause_state(self) -> None:
        state = self._engine.run_state
        self._actions.set_enabled("play", state != EngineRunState.PLAY)
        self._actions.set_enabled("pause", state == EngineRunState.PLAY)
        self._actions.set_enabled("stop", state != EngineRunState.EDIT)

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
        self._refresh_all()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self._is_closing = True
        self._timer.cancel_all()
        self._coordinator.shutdown()
        self._ui.shutdown()
        self._root.destroy()

    def run(self) -> None:
        """Start the Tk main loop."""
        self._root.mainloop()
