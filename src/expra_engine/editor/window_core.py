"""Toolkit-independent editor window logic.

Holds the editor composition-root behaviour that does not depend on a GUI
toolkit: selection, hierarchy/inspector/viewport callbacks, undo/redo, Play/
Pause/Stop, autosave scheduling, coordinated presentation and shutdown order.

The concrete frontend (the Qt ``EditorWindow``) subclasses ``EditorWindowCore``
and provides only the shell hooks declared below. Panels expose this
presentation API (``hierarchy.render/select/select_many``, ``inspector.render/render_world``,
``viewport.render/render_world/update_selection``, ``console.log``).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.coordinators.button_coordinator import ButtonCoordinator
from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.core.component import TransformComponent, registered_component_types
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.core.scene.scene_instance import SceneInstanceComponent
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.builtin_features import build_builtin_features
from expra_engine.editor.commands import (
    AddComponentCommand,
    Command,
    CreateEntityCommand,
    DeleteEntityCommand,
    MakeSceneInstanceUniqueCommand,
    RenameEntityCommand,
    SetExposedValueCommand,
    SetInstanceOverrideCommand,
    ToggleEnabledCommand,
    TransformEntityCommand,
)
from expra_engine.editor.contributions import (
    ContributionRegistry,
    EditorContext,
    ShortcutRegistry,
)
from expra_engine.editor.dialog_provider import DialogProvider
from expra_engine.editor.document_actions import EditorDocumentSurface
from expra_engine.editor.interactions import delete_selection, duplicate_selection
from expra_engine.editor.mutation_policy import (
    MutationVerdict,
    decide_entity_mutation,
    route_instance_override_target,
)
from expra_engine.editor.normal_map_actions import NormalMapEditorActionsMixin
from expra_engine.editor.preferences import PreferencesStore
from expra_engine.editor.project_workflow import ProjectWorkflow
from expra_engine.editor.render_targets import RenderTargetRegistry
from expra_engine.editor.script_actions import ScriptEditorActionsMixin
from expra_engine.editor.world_authoring import WorldEditorActionsMixin
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.input import PhysicalInput
from expra_engine.runtime.script_component import ScriptComponent

LOGGER = logging.getLogger(__name__)
_VIEWPORT_CAMERA_SAVE_DEBOUNCE_MS = 400


class EditorWindowCore(
    EditorDocumentSurface,
    WorldEditorActionsMixin,
    NormalMapEditorActionsMixin,
    ScriptEditorActionsMixin,
):
    """Editor logic shared by every GUI frontend."""

    # Provided by the concrete frontend's constructor (the Qt shell).
    _engine: Engine
    _active_document: ActiveDocument
    _root: Any
    _console: Any
    _hierarchy: Any
    _inspector: Any
    _viewport: Any
    _timer: Any
    _delivery_queue: Any
    _dialog_provider: DialogProvider
    _preferences_path: Path
    _preferences_store: PreferencesStore

    def _init_services(self, *, runtime_preview_class: Any) -> None:
        """Wire coordinators, contributions, project workflow and the preview loop.

        The shell must already have set ``_root``, ``_engine``, ``_delivery_queue``,
        ``_timer``, ``_pending_timer_ids``, ``_is_closing`` and ``_dialog_provider``.
        """
        # Shared across the whole application session -- AppCoordinator,
        # ButtonCoordinator, UICoordinator, the viewport's render
        # extraction/plan/pixel bridge, and the Engine (injected below) --
        # so a single snapshot() reports app/ui/runtime/render/editor
        # metrics together (see performance_probe's use of this for
        # regression data).
        self._observer = ObservabilityWatcher()
        self._engine.observer = self._observer

        # Coordinators
        self._coordinator = AppCoordinator(deliver=self._delivery_queue, observer=self._observer)
        self._actions = ButtonCoordinator(observer=self._observer)
        self._ui = UICoordinator(observer=self._observer)
        self._editor_context = EditorContext(
            engine=self._engine,
            actions=self._actions,
            ui=self._ui,
            app=self._coordinator,
            project=self._engine.project,
        )
        self._shortcuts = ShortcutRegistry()
        self._contributions = ContributionRegistry(
            self._actions,
            context=self._editor_context,
            shortcuts=self._shortcuts,
        )
        self._render_targets = RenderTargetRegistry()
        self._render_generations: dict[str, int] = {"inspector": 0}
        self._render_owners: dict[str, str | None] = {"inspector": None}
        self._project_workflow = ProjectWorkflow(self, dialog_provider=self._dialog_provider)
        self._runtime_preview = runtime_preview_class(
            self._root,
            self._engine,
            lambda: self._request_render(
                "viewport", (self._engine.active_scene, None), priority=20
            ),
            observer=self._observer,
            on_world_startup_diagnostic=lambda message: self._console.log(
                f"[World] {message}", level="error"
            ),
            on_world_startup_error=self._act_stop,
            on_runtime_error=lambda message: self._console.log(message, level="error"),
        )

    # ------------------------------------------------------------------
    # Shell hooks -- the only toolkit-specific surface the logic needs
    # ------------------------------------------------------------------

    def _set_window_title(self, title: str) -> None:
        raise NotImplementedError

    def _after(self, delay_ms: int, callback: Callable[[], None]) -> Any:
        raise NotImplementedError

    def _cancel_after(self, handle: Any) -> None:
        raise NotImplementedError

    def _bind_shortcuts(self) -> None:
        raise NotImplementedError

    def _preview_lighting_enabled(self) -> bool:
        raise NotImplementedError

    def _apply_save_label(self, label: str) -> None:
        raise NotImplementedError

    @property
    def _dialogs(self) -> DialogProvider:
        return self._dialog_provider

    def _forward_runtime_key(self, phase: str, key: object) -> None:
        if self._engine.run_state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return
        control = str(key).lower()
        if not control:
            return
        observer = self._observer
        token = observer.begin("runtime:input:dispatch") if observer is not None else None
        transitions: tuple[Any, ...] = ()
        try:
            transitions = getattr(self._engine.input_map, phase)(PhysicalInput("keyboard", control))
            for action_event in transitions:
                self._engine.signal(action_event)
        finally:
            if observer is not None:
                observer.increment("runtime:input:dispatch", "physical_inputs")
                observer.increment("runtime:input:dispatch", "action_events", len(transitions))
                if token is not None:
                    observer.finish(token)

    def _on_asset_open(self, entry: Any) -> None:
        self._project_workflow.open_asset(entry)

    def _register_render_targets(self) -> None:
        self._render_targets.register("hierarchy", self._render_hierarchy)
        self._render_targets.register("inspector", self._render_inspector)
        self._render_targets.register("viewport", self._render_viewport)
        self._render_targets.register("toolbar", self._render_toolbar)

    def _render_hierarchy(self, intent: RenderIntent) -> None:
        self._hierarchy.render(intent.payload)

    def _render_inspector(self, intent: RenderIntent) -> None:
        if self._editing_world_document():
            self._inspector.render_world(
                self._active_document.document,
                self._selected_id,
            )
            return
        self._inspector.render(intent.payload)

    def _render_toolbar(self, _intent: RenderIntent) -> None:
        self._update_play_pause_state()

    def _act_preview_lighting_changed(self) -> None:
        """Refresh the edit viewport without changing authored camera settings."""
        self._request_render(
            "viewport",
            (self._engine.active_scene, tuple(self._selected_ids)),
            priority=10,
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
        self._bind_shortcuts()
        self._update_play_pause_state()

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
        self._project_workflow.stop_project()
        if self._engine.stop():
            self._console.log("[Engine] Stopped — scene restored", level="info")
        self._project_workflow.restore_after_run_project()
        self._update_play_pause_state()
        self._present_all()

    def _start_autosave(self) -> None:
        """Schedule recurring silent saves using the configured preference."""
        interval_ms = max(1, int(self._preferences.autosave_interval_ms))

        def autosave() -> None:
            self._autosave_after_id = None
            self._act_save_scene_silent()
            if not self._is_closing:
                self._autosave_after_id = self._after(interval_ms, autosave)

        if self._autosave_after_id is not None:
            self._cancel_after(self._autosave_after_id)
        self._autosave_after_id = self._after(interval_ms, autosave)

    def _act_add_entity(self) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        self._on_hierarchy_create()

    def _act_delete_entity(self) -> None:
        if len(self._selected_ids) == 1:
            self._on_hierarchy_delete(self._selected_ids[0])
        elif self._selected_ids:
            delete_selection(self)

    def _act_duplicate_selection(self) -> None:
        duplicate_selection(self)

    def _selected_source_path(self) -> str | None:
        """Return the source Scene path for the selected entity, if it is linked."""
        scene = self._engine.edit_scene
        primary = self._selected_id
        if scene is None or primary is None:
            return None
        origin = scene.entity_origin(primary)
        if origin.source_path:
            return origin.source_path
        if origin.kind == "instance_root":
            entity = scene.find_entity(primary)
            component = entity.get_component(SceneInstanceComponent) if entity is not None else None
            return component.source_path if component is not None else None
        return None

    def _act_open_instance_source(self) -> None:
        """Open the source Scene backing the selected linked entity or instance root."""
        if self._engine.run_state != EngineRunState.EDIT:
            return
        source_path = self._selected_source_path()
        if source_path is None:
            self._console.log("[Editor] Selection is not linked to a source scene", level="warning")
            return
        self._project_workflow.open_document(source_path)

    def _act_make_instance_unique(self) -> None:
        """Detach the selected instance (or its owning instance) from its source."""
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        project = self._engine.project
        primary = self._selected_id
        if scene is None or primary is None or project is None:
            return
        origin = scene.entity_origin(primary)
        if origin.kind == "materialized":
            root_id = origin.instance_root_id
        elif origin.kind == "instance_root":
            root_id = primary
        else:
            self._console.log("[Editor] Selection is not a scene instance", level="warning")
            return
        if root_id is None:
            return
        command = MakeSceneInstanceUniqueCommand(
            scene, root_id, lambda path: project.load_scene(path)
        )
        self._command_stack.push(command)
        self._update_undo_redo_state()
        self._console.log("[Editor] Made scene instance unique")
        self._present_all()

    def _on_hierarchy_select(self, ids: Sequence[str]) -> None:
        """Central selection setter: dedupes, drops dead ids, updates dependent action state."""
        scene, entity = self._set_selection_state(ids)
        self._present_selection(scene, entity)

    def _set_selection_state(self, ids: Sequence[str]) -> tuple[Scene | None, Any | None]:
        """Set the canonical selection and its action state without presenting it."""
        if self._apply_world_selection(ids):
            return None, None
        scene = self._engine.active_scene
        valid = tuple(
            dict.fromkeys(i for i in ids if scene is None or scene.find_entity(i) is not None)
        )
        self._selected_ids = valid
        primary_id = valid[0] if valid else None
        self._actions.set_enabled("delete_entity", bool(valid))
        self._actions.set_enabled("duplicate_selection", bool(valid))
        entity = scene.find_entity(primary_id) if scene and primary_id else None
        has_script = bool(
            entity is not None
            and any(isinstance(component, ScriptComponent) for component in entity.components)
        )
        self._actions.set_enabled("attach_script", primary_id is not None and not has_script)
        self._actions.set_enabled("remove_script", has_script)
        return scene, entity

    def _linked_mutation_rejected(self, entity_id: str, operation: str) -> bool:
        """Return True (and log a warning) when the edit targets linked content."""
        scene = self._engine.edit_scene
        if scene is None:
            return False
        decision = decide_entity_mutation(scene, entity_id, operation)
        if decision.verdict is MutationVerdict.REJECT_LINKED:
            message = decision.reason or "Linked content is read-only"
            self._console.log(f"[Editor] {message}", level="warning")
            return True
        return False

    def _on_add_component(self, component_name: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT or self._selected_id is None:
            return
        scene = self._engine.edit_scene
        entity = scene.find_entity(self._selected_id) if scene else None
        component_type = dict(registered_component_types()).get(component_name)
        if entity is None or component_type is None:
            return
        if self._linked_mutation_rejected(entity.entity_id, "add_component"):
            return
        if any(isinstance(component, component_type) for component in entity.components):
            return
        try:
            self._command_stack.push(AddComponentCommand(scene, entity.entity_id, component_type))
        except TypeError as exc:
            self._dialogs.show_error("Add Component", str(exc))
            return
        self._console.log(f"[Editor] Added {component_name} to {entity.name}")
        self._present_all()

    def _on_hierarchy_create(self) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            scene = Scene("New Scene")
            self._engine.set_scene(scene)
        entity = scene.create_entity("Entity")
        entity.add_component(TransformComponent())
        self._command_stack.push(CreateEntityCommand(scene, entity))
        self._update_undo_redo_state()
        self._set_selection_state((entity.entity_id,))
        self._console.log(f"[Editor] Created entity: {entity.name}")
        self._present_all()

    def _on_hierarchy_delete(self, entity_id: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        if self._linked_mutation_rejected(entity_id, "delete"):
            return
        cmd = DeleteEntityCommand(scene, entity)
        self._command_stack.push(cmd)
        self._console.log(f"[Editor] Deleted entity: {entity.name}")
        self._set_selection_state(
            tuple(selected_id for selected_id in self._selected_ids if selected_id != entity_id)
        )
        self._update_undo_redo_state()
        self._present_all()

    _TRANSFORM_FIELDS = ("x", "y", "rotation", "scale_x", "scale_y")

    def _on_transform_change(self, entity_id: str, field: str, value: float) -> None:
        if self._engine.run_state != EngineRunState.EDIT or field not in self._TRANSFORM_FIELDS:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        if self._linked_mutation_rejected(entity_id, "transform"):
            return
        transform = entity.get_component(TransformComponent)
        if transform is None:
            return
        old = tuple(getattr(transform, name) for name in self._TRANSFORM_FIELDS)
        index = self._TRANSFORM_FIELDS.index(field)
        new = tuple(value if i == index else old[i] for i in range(len(old)))
        if new == old:
            return
        self._command_stack.push(TransformEntityCommand(scene, entity_id, old, new))
        self._update_undo_redo_state()
        self._request_render("viewport", (scene, self._selected_ids), priority=10)

    def _on_entity_rename(self, entity_id: str, new_name: str) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None:
            return
        if self._linked_mutation_rejected(entity_id, "rename"):
            return
        cmd = RenameEntityCommand(entity, entity.name, new_name)
        self._command_stack.push(cmd)
        self._update_undo_redo_state()
        self._ui.begin_batch()
        self._request_render("hierarchy", scene, priority=20)
        self._request_render("viewport", (scene, self._selected_ids), priority=10)
        self._ui.end_batch()
        self._hierarchy.select(entity_id)

    def _on_entity_toggle(self, entity_id: str, enabled: bool) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None:
            return
        entity = scene.find_entity(entity_id)
        if entity is None or entity.enabled == enabled:
            return
        if self._linked_mutation_rejected(entity_id, "toggle_enabled"):
            return
        self._command_stack.push(ToggleEnabledCommand(scene, entity_id, entity.enabled, enabled))
        self._update_undo_redo_state()
        self._present_all()

    def _on_script_value_change(
        self, entity_id: str, component_index: int, field: str, value: Any
    ) -> None:
        if self._engine.run_state != EngineRunState.EDIT:
            return
        scene = self._engine.edit_scene
        if scene is None or scene.find_entity(entity_id) is None:
            return
        decision = decide_entity_mutation(scene, entity_id, "set_exposed_value")
        if decision.verdict is MutationVerdict.ROUTE_INSTANCE_OVERRIDE:
            target = route_instance_override_target(scene, entity_id)
            if isinstance(target, str):
                self._console.log(f"[Editor] {target}", level="warning")
                return
            self._command_stack.push(SetInstanceOverrideCommand(scene, entity_id, field, value))
        elif decision.verdict is MutationVerdict.REJECT_LINKED:
            self._console.log(f"[Editor] {decision.reason or 'Linked content is read-only'}", level="warning")
            return
        else:
            self._command_stack.push(
                SetExposedValueCommand(scene, entity_id, component_index, field, value)
            )
        self._update_undo_redo_state()
        self._present_all()

    def _on_viewport_entity_click(self, ids: tuple[str, ...], extend: bool) -> None:
        """Plain click replaces selection; Shift/Ctrl toggles a single entity or extends (box-select)."""
        if not extend:
            new_ids = ids
        elif len(ids) == 1 and ids[0] in self._selected_ids:
            new_ids = tuple(i for i in self._selected_ids if i != ids[0])
        else:
            new_ids = tuple(dict.fromkeys((*self._selected_ids, *ids)))
        self._on_hierarchy_select(new_ids)

    def _save_viewport_camera(self, values: dict[str, object]) -> None:
        # Pan/zoom/rotate fire this on every mouse-motion tick -- update the
        # in-memory value immediately (cheap) but debounce the actual disk
        # write (atomic write + fsync, measured ~4-8ms) so a sustained drag
        # doesn't serialize preferences dozens of times per second on the GUI
        # main thread. The trailing write always lands: _on_close flushes any
        # still-pending write before cancel_all() would otherwise drop it.
        self._preferences = replace(self._preferences, viewport_camera=values)
        self._timer.cancel(self._viewport_camera_save_after_id)
        self._viewport_camera_save_after_id = self._timer.schedule(
            _VIEWPORT_CAMERA_SAVE_DEBOUNCE_MS, self._flush_viewport_camera_prefs
        )

    def _flush_viewport_camera_prefs(self) -> None:
        self._viewport_camera_save_after_id = None
        self._preferences_store.save(self._preferences_path, self._preferences)

    def _refresh_viewport(self) -> None:
        self._request_render(
            "viewport",
            (self._engine.active_scene, self._selected_ids),
            priority=10,
        )

    def _refresh_all(self) -> None:
        self._present_all()

    def _push_spatial_command(self, command: Command) -> None:
        """Commit one viewport drag gesture (move/rotate/scale) as one undo entry."""
        self._command_stack.push(command)
        self._console.log(f"[Editor] {command.description}")
        self._update_undo_redo_state()
        self._present_all()

    def _update_play_pause_state(self) -> None:
        state = self._engine.run_state
        entity_editable = (
            state == EngineRunState.EDIT and self._active_document.kind is not DocumentKind.WORLD
        )
        self._actions.set_enabled("play", state != EngineRunState.PLAY)
        self._actions.set_enabled("pause", state == EngineRunState.PLAY)
        self._actions.set_enabled(
            "stop", state != EngineRunState.EDIT or self._project_process_running()
        )
        self._actions.set_enabled("add_entity", entity_editable)
        self._actions.set_enabled("delete_entity", entity_editable and bool(self._selected_ids))
        self._actions.set_enabled(
            "duplicate_selection", entity_editable and bool(self._selected_ids)
        )
        self._update_project_actions()

    def _project_process_running(self) -> bool:
        """True while a Run Project child is alive (the engine itself stays in edit state)."""
        workflow = getattr(self, "_project_workflow", None)
        controller = getattr(workflow, "_project_process_controller", None)
        return controller is not None and controller.process is not None

    def _update_project_actions(self) -> None:
        has_project = self._engine.project is not None
        self._actions.set_enabled("save_document", has_project)
        self._actions.set_enabled("save_scene", has_project)
        self._actions.set_enabled("close_project", has_project)
        self._actions.set_enabled("new_script", has_project)
        self._actions.set_enabled("import_asset", has_project)
        self._actions.set_enabled("configure_input", has_project)
        self._actions.set_enabled("editor.export_game", has_project)
        self._refresh_typed_save_labels()

    def _create_default_scene(self) -> None:
        scene = Scene("Sample Scene")
        entity = scene.create_entity("Camera")
        entity.add_component(TransformComponent(x=0, y=0))
        entity2 = scene.create_entity("Player")
        entity2.add_component(TransformComponent(x=80, y=-40))
        self._engine.set_scene(scene)
        self._active_document.open(scene)
        self._console.log("[Editor] Expra Engine started")
        self._console.log(f"[Editor] Loaded scene: {scene.name}")
        self._present_all()

    def _request_render(
        self,
        target: str,
        payload: object,
        *,
        owner_id: str | None = None,
        components: frozenset[str] = frozenset(),
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
            components=components,
            payload=payload,
            payload_set=True,
            priority=priority,
        )
        self._ui.request(intent, self._render_targets.callback_for(target))

    def _render_viewport(self, intent: RenderIntent) -> None:
        payload = intent.payload
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        scene, selected_ids = payload
        ids = tuple(selected_ids) if selected_ids else ()
        primary_id = ids[0] if ids else None
        runtime_preview = self._engine.run_state in (EngineRunState.PLAY, EngineRunState.PAUSED)
        world_system = self._engine.world_streaming_system
        _ws_active = runtime_preview and world_system is not None
        transition_alpha = world_system.transition_alpha if world_system is not None and _ws_active else 0.0
        if not runtime_preview and self._editing_world_document():
            self._viewport.render_world(self._active_document.document, primary_id)
            return
        if (
            intent.components == frozenset({"selection"})
            and scene is self._viewport._scene
            and not runtime_preview
        ):
            self._viewport.update_selection(primary_id, frozenset(ids))
            return
        self._viewport.render(
            scene,
            primary_id,
            selected_ids=frozenset(ids),
            editor_overlays=not runtime_preview,
            interpolator=self._engine.transform_interpolator if runtime_preview else None,
            interpolation_fraction=self._engine.interpolation_fraction if runtime_preview else 0.0,
            animated_players=self._engine.animated_sprite_system.players,
            world_transition_alpha=transition_alpha,
            preview_lighting=(None if runtime_preview else self._preview_lighting_enabled()),
            modulation_entity_ids=(
                world_system.environment_entity_ids
                if world_system is not None and _ws_active
                else None
            ),
        )

    def _present_selection(self, scene: Scene | None, entity: Any) -> None:
        self._hierarchy.select_many(self._selected_ids)
        self._ui.begin_batch()
        self._request_render("inspector", entity, owner_id=self._selected_id, priority=30)
        self._request_render(
            "viewport",
            (scene, self._selected_ids),
            components=frozenset({"selection"}),
            priority=10,
        )
        self._ui.end_batch()

    def _present_all(self) -> None:
        scene, entity = self._set_selection_state(self._selected_ids)
        hierarchy_document = (
            self._active_document.document
            if self._engine.run_state is EngineRunState.EDIT
            else self._engine.active_scene
        )
        self._ui.begin_batch()
        self._request_render("hierarchy", hierarchy_document, priority=20)
        self._request_render("inspector", entity, owner_id=self._selected_id, priority=30)
        self._request_render("viewport", (scene, self._selected_ids), priority=10)
        self._request_render("toolbar", self._engine.run_state, priority=40)
        self._ui.end_batch()
        self._hierarchy.select_many(self._selected_ids)

    def _on_close(self) -> None:
        self._runtime_preview.stop()
        workflow = getattr(self, "_project_workflow", None)
        if workflow is not None:
            workflow.stop_project()
        self._is_closing = True
        if self._autosave_after_id is not None:
            self._cancel_after(self._autosave_after_id)
            self._autosave_after_id = None
        self._persist_window_geometry()
        if self._viewport_camera_save_after_id is not None:
            self._timer.cancel(self._viewport_camera_save_after_id)
            self._viewport_camera_save_after_id = None
            with contextlib.suppress(OSError, TypeError, ValueError):
                self._preferences_store.save(self._preferences_path, self._preferences)
        self._timer.cancel_all()
        self._contributions.stop_all()
        self._delivery_queue.close()
        self._coordinator.shutdown()
        self._ui.shutdown()
        self._destroy_shell()

    def _persist_window_geometry(self) -> None:
        raise NotImplementedError

    def _destroy_shell(self) -> None:
        raise NotImplementedError
