"""Toolkit-independent editor viewport logic.

Everything except widget construction: render-target building, retained canvas
item model, camera controls, selection, spatial editing and input handlers. The
canvas it draws to only needs a small canvas-shaped surface (``create_*``,
``coords``, ``itemconfig``, ``delete``, ``bind`` ...) that ``QtCanvas``
(``editor/qt/canvas.py``) implements over a ``QGraphicsScene``; tests substitute
fake canvases.

This is the architectural seam for the rendering backend: the retained canvas
model is an editor-side overlay while the pixel layer comes from the canonical
Pygame renderer. The seam is the ``render_scene`` method.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import replace
from typing import Any

from expra_engine.core.camera import Camera2D
from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.core.world import World
from expra_engine.observability import observe_stage
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderFrame,
    RenderItem,
    RenderSpace,
    Transform,
)
from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer
from expra_engine.ui.spatial_edit import SpatialEditController
from expra_engine.ui.viewport_camera import (
    ViewportCamera,
    compute_frame_fit,
)
from expra_engine.ui.viewport_camera_overlay import draw_camera_overlay
from expra_engine.ui.viewport_input import ViewportInputMixin
from expra_engine.ui.viewport_items import CanvasItemEntry, ViewportItemLayer
from expra_engine.ui.viewport_lighting import LightGizmo, update_light_gizmo
from expra_engine.ui.viewport_markers import (
    EntityMarkerFrame,
    MarkerEntry,
    draw_entity_markers,
    prepare_entity_markers,
    update_marker_selection,
)
from expra_engine.ui.viewport_overlays import ColliderCanvasEntry, draw_collider_overlays
from expra_engine.ui.viewport_render_target import (
    EditorRenderTarget,
    build_editor_render_target,
    reproject_editor_render_target,
)
from expra_engine.ui.world_overlay import WorldOverlayMixin


class _EntityNameLookup(Mapping[str, str]):
    """Read entity names through the viewport's existing O(1) entity map."""

    def __init__(self, entities: dict[str, Any]) -> None:
        self._entities = entities

    def __getitem__(self, entity_id: str) -> str:
        return self._entities[entity_id].name

    def __iter__(self) -> Iterator[str]:
        return iter(self._entities)

    def __len__(self) -> int:
        return len(self._entities)


class ViewportCore(ViewportInputMixin, WorldOverlayMixin):
    """Viewport behaviour shared by every GUI frontend."""

    _ENTITY_RADIUS = 12

    def _init_viewport(
        self,
        canvas: Any,
        *,
        colors: dict[str, str],
        on_entity_click: Any = None,
        camera_state: dict[str, object] | None = None,
        on_camera_change: Any = None,
        resource_service: Any | None = None,
        observer: Any | None = None,
        on_transform_commit: Any = None,
        image_factory: Any,
    ) -> None:
        c = colors
        self._on_entity_click = on_entity_click
        self._on_camera_change = on_camera_change
        self._colors = c
        self._scene: Scene | None = None
        self._world: World | None = None
        self._world_style_items: dict[str, list[tuple[int, str]]] = {}
        self._world_drawn = False
        self._selected_id: str | None = None
        self._selected_ids_set: frozenset[str] = frozenset()
        self._target = EditorRenderTarget(RenderFrame(), (), None)
        self._target_dirty = False
        self._camera = ViewportCamera()
        self._editor_overlays = True
        self._interpolator: Any | None = None
        self._interpolation_fraction = 0.0
        self._world_transition_alpha = 0.0
        self._preview_lighting: bool | None = None
        self._resolved_runtime_camera: OrthographicCamera | None = None
        self._primary_level_entity_ids: tuple[str, ...] | None = None
        self._observer = observer
        self._pixel_renderer = EditorPixelRenderer(
            resource_service, observer=observer, image_factory=image_factory
        )
        self._pixel_image: Any | None = None
        if camera_state:
            self._camera.apply_dict(camera_state)
        self._pan_anchor: tuple[float, float] | None = None
        self._space_held = False
        self._space_pan_anchor: tuple[float, float] | None = None

        # Render-loop state
        self._redraw_pending = False  # idle-scheduler gate to cap redraw rate
        self._grid_dirty = True  # grid/axis needs rebuild (camera moved or canvas resized)
        self._grid_size: tuple[int, int] | None = None
        self._grid_item_ids: list[int] = []
        self._grid_axis_ids: tuple[int, int] | None = None
        self._canvas_items: dict[str, CanvasItemEntry] = {}  # compatibility view of retained items
        self._marker_entries: dict[str, MarkerEntry] = {}  # retained icon-marker items
        self._selection_item_ids: list[int] = []
        self._collider_overlay_entries: dict[str, ColliderCanvasEntry] = {}
        self._camera_overlay_ids: tuple[int, ...] = ()
        self._no_scene_text_id: int | None = None
        self._light_gizmo: LightGizmo | None = None
        self._entity_map: dict[str, Any] = {}  # built once per render() call; O(1) lookup
        self._entity_names: Mapping[str, str] = _EntityNameLookup(self._entity_map)
        self._items_by_id: dict[str, RenderItem] = {}
        self._visual_ids: frozenset[str] = frozenset()  # frame renderables, including offscreen items
        self._marker_frame: EntityMarkerFrame | None = None
        self._preview_render_items: dict[str, tuple[RenderItem, ...]] = {}
        self._preview_dirty_ids: set[str] = set()
        self._preview_collider_positions: dict[str, tuple[float, float]] = {}
        self._modulation_entity_ids: tuple[str, ...] | None = None
        self._pending_camera_pan_delta: tuple[float, float] | None = (0.0, 0.0)

        self._canvas = canvas
        self._item_layer = ViewportItemLayer(canvas, self._colors, self._camera)
        self._canvas_items = self._item_layer.entries
        self._pixel_image_item = self._canvas.create_image(
            0, 0, anchor="nw", state="hidden", tags="runtime_pixels"
        )
        self._spatial_edit = SpatialEditController(
            camera=self._camera,
            canvas=self._canvas,
            get_scene=lambda: self._scene,
            get_selected_ids=lambda: tuple(self._selected_ids_set),
            push_command=on_transform_commit or (lambda _command: None),
            request_redraw=self._schedule_redraw,
            on_transform_preview=self._preview_transform_items,
        )
        # <Button-1> and <ButtonPress-1> are the SAME canvas event sequence --
        # binding both without add="+" silently replaces the first with the
        # second, which is what made _on_click's empty-space deselect dead
        # code in the live app (only entity tag clicks worked). Every
        # Button-1/ButtonPress-1 binding below uses add="+" so they compose.
        self._canvas.bind("<Button-1>", self._on_click, add="+")
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_motion)
        # Wheel zoom — covers Windows/macOS (<MouseWheel>) and Linux X11 (<Button-4/5>)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<Button-4>", self._on_wheel)
        self._canvas.bind("<Button-5>", self._on_wheel)
        # Camera rotation (existing)
        self._canvas.bind("<KeyPress-q>", lambda _event: self._rotate_camera(-15.0))
        self._canvas.bind("<KeyPress-e>", lambda _event: self._rotate_camera(15.0))
        self._canvas.bind("<KeyPress-r>", lambda _event: self._reset_camera())
        # Keyboard zoom: Ctrl++ / Ctrl+- / Ctrl+0
        self._canvas.bind("<Control-equal>", lambda _e: self._kb_zoom(1.25))
        self._canvas.bind("<Control-minus>", lambda _e: self._kb_zoom(0.8))
        self._canvas.bind("<Control-0>", lambda _e: self._reset_camera())
        self._canvas.bind("<Control-KP_Add>", lambda _e: self._kb_zoom(1.25))
        self._canvas.bind("<Control-KP_Subtract>", lambda _e: self._kb_zoom(0.8))
        # Frame commands: F = frame selected, Home = frame scene
        self._canvas.bind("<f>", lambda _e: self._frame_selected_key())
        self._canvas.bind("<F>", lambda _e: self._frame_selected_key())
        self._canvas.bind("<Home>", lambda _e: self._frame_scene_key())
        # Space + left-drag pan
        self._canvas.bind("<KeyPress-space>", self._on_space_down)
        self._canvas.bind("<KeyRelease-space>", self._on_space_up)
        self._canvas.bind("<ButtonPress-1>", self._on_lmb_press_for_pan, add="+")
        self._canvas.bind("<B1-Motion>", self._on_lmb_motion_for_pan, add="+")
        # Spatial editing: box-select-start (empty canvas) / drag continue+commit.
        self._canvas.bind("<ButtonPress-1>", self._on_button1_press_for_selection, add="+")
        self._canvas.bind("<B1-Motion>", self._on_b1_motion_for_selection, add="+")
        self._canvas.bind("<ButtonRelease-1>", self._on_button1_release)
        self._canvas.bind("<Escape>", lambda _e: self._spatial_edit.cancel_drag())

    def render(
        self,
        scene: Scene | None,
        selected_id: str | None = None,
        *,
        selected_ids: frozenset[str] | None = None,
        editor_overlays: bool = True,
        interpolator: Any | None = None,
        interpolation_fraction: float = 0.0,
        animated_players: dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
        world_transition_alpha: float = 0.0,
        preview_lighting: bool | None = None,
        modulation_entity_ids: Any | None = None,
        primary_level_entity_ids: Iterable[str] | None = None,
        resolved_camera: OrthographicCamera | None = None,
    ) -> None:
        """Redraw the viewport for ``scene``. Called on the main thread."""
        if self._world is not None:
            self._canvas.delete("world")
            self._world_style_items.clear()
            self._world_drawn = False
        self._world = None
        scene_changed = scene is not None and (
            self._scene is None or self._scene.scene_id != scene.scene_id
        )
        overlays_changed = editor_overlays != self._editor_overlays
        self._scene = scene
        self._selected_id = selected_id
        self._selected_ids_set = (
            frozenset(selected_ids)
            if selected_ids is not None
            else (frozenset({selected_id}) if selected_id else frozenset())
        )
        self._editor_overlays = editor_overlays
        self._interpolator = interpolator
        self._interpolation_fraction = interpolation_fraction
        self._world_transition_alpha = max(0.0, min(1.0, float(world_transition_alpha)))
        self._preview_lighting = preview_lighting
        self._resolved_runtime_camera = resolved_camera
        self._primary_level_entity_ids = (
            tuple(primary_level_entity_ids) if primary_level_entity_ids is not None else None
        )
        self._modulation_entity_ids = (
            tuple(modulation_entity_ids) if modulation_entity_ids is not None else None
        )
        self._animated_players = animated_players

        if scene_changed and scene is not None and editor_overlays:
            self._pending_camera_pan_delta = None
            self._camera.apply_dict(scene.camera)
            self._grid_dirty = True
            self._clear_all_items()
            self._pixel_renderer.clear()
        if overlays_changed:
            self._grid_dirty = True

        # Build entity map once — replaces O(n²) find_entity calls in _draw_render_item.
        self._entity_map = {e.entity_id: e for e in scene.entities} if scene is not None else {}
        self._entity_names = _EntityNameLookup(self._entity_map)

        width, height = self._canvas.viewport_size()
        self._pending_camera_pan_delta = None
        self._preview_render_items.clear()
        self._preview_dirty_ids.clear()
        self._preview_collider_positions.clear()
        self._target = build_editor_render_target(
            scene,
            viewport=(max(1, width), max(1, height)),
            selected_id=selected_id,
            # During Play/Paused the rendered frame must come from the scene's
            # own saved camera (position, width, rotation), not the editor's
            # live pannable authoring camera -- passing None here makes
            # build_editor_render_target derive the preview camera purely from
            # scene.camera, so Play is deterministic across Play/Stop/Play and
            # never inherits whatever pan/zoom the author happened to leave
            # the Edit viewport at. Stop never touches self._camera, so the
            # authoring camera is implicitly preserved/restored for free.
            camera=self._camera if editor_overlays else None,
            resolved_camera=resolved_camera,
            interpolator=interpolator,
            interpolation_fraction=interpolation_fraction,
            animated_players=animated_players,
            observer=self._observer,
            preview_lighting=self._preview_lighting,
            modulation_entity_ids=self._modulation_entity_ids,
            primary_level_entity_ids=self._primary_level_entity_ids,
        )
        self._visual_ids = frozenset(item.key for item in self._target.frame.items)
        with observe_stage(self._observer, "editor.viewport.marker_prepare"):
            self._marker_frame = (
                prepare_entity_markers(
                    scene,
                    self._visual_ids,
                    measure_text=getattr(self._canvas, "measure_text", None),
                    camera=self._camera,
                    viewport=(max(1, width), max(1, height)),
                )
                if scene is not None and editor_overlays
                else None
            )
        self._items_by_id = {item.key: item for item in self._target.items}
        self._target_dirty = False
        self._redraw()

    def render_world(self, world: World, selected_id: str | None = None) -> None:
        """Draw lightweight World descriptors without loading referenced Levels."""
        previous_world = self._world
        previous_selection = self._selected_id
        world_changed = previous_world is not world
        if world_changed:
            self._pending_camera_pan_delta = None
        self._world = world
        self._scene = None
        self._selected_id = selected_id
        self._selected_ids_set = frozenset({selected_id}) if selected_id else frozenset()
        if world_changed:
            self._entity_map = {}
            self._entity_names = _EntityNameLookup(self._entity_map)
            self._items_by_id = {}
            self._visual_ids = frozenset()
            self._marker_frame = None
            self._target = EditorRenderTarget(RenderFrame(), (), None)
            self._target_dirty = False
            self._editor_overlays = True
            self._interpolator = None
            self._world_transition_alpha = 0.0
            self._pixel_renderer.clear()
            self._canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")
            self._pixel_image = None
            self._clear_all_items()
            self._world_style_items.clear()
            self._world_drawn = False
            self._grid_dirty = True
            self._schedule_redraw()
        elif not self._world_drawn:
            self._schedule_redraw()
        elif previous_selection != selected_id:
            if previous_selection is not None:
                self._restyle_world_items(previous_selection, selected=False)
            if selected_id is not None:
                self._restyle_world_items(selected_id, selected=True)

    def update_selection(
        self, selected_id: str | None, selected_ids: frozenset[str] = frozenset()
    ) -> None:
        """Update edit-mode selection overlays without rebuilding the scene frame."""
        if not self._editor_overlays or self._scene is None:
            self.render(self._scene, selected_id, selected_ids=selected_ids)
            return
        previous_id = self._selected_id
        ids = selected_ids or (frozenset({selected_id}) if selected_id else frozenset())
        if previous_id == selected_id and ids == self._selected_ids_set:
            return

        self._selected_id = selected_id
        self._selected_ids_set = ids
        self._target = replace(self._target, selected_id=selected_id)
        self._item_layer.update_selection(
            previous_id,
            selected_id,
            items_by_id=self._items_by_id,
            entity_names=self._entity_names,
            render_context=self._target.render_context,
            editor_overlays=self._editor_overlays,
        )
        for entity_id in dict.fromkeys((previous_id, selected_id)):
            if entity_id is None:
                continue
            marker = self._marker_entries.get(entity_id)
            if marker is not None:
                update_marker_selection(
                    self._canvas,
                    self._colors,
                    marker,
                    entity_id == selected_id,
                )
        self._light_gizmo = update_light_gizmo(
            self._canvas,
            self._scene,
            selected_id if self._editor_overlays else None,
            self._camera,
            self._colors,
            self._light_gizmo,
        )

    def set_resource_service(self, resource_service: Any | None) -> None:
        """Replace project resources and discard backend-owned decoded textures."""
        if resource_service is self._pixel_renderer.resource_service:
            return
        self._pixel_renderer.set_resource_service(resource_service)
        if hasattr(self, "_canvas"):
            self._canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")
            self._pixel_image = None
            self._schedule_redraw()

    def pan(self, x: float, y: float) -> None:
        with observe_stage(self._observer, "editor.viewport.camera_update"):
            self._pan_camera(x, y)
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()

    def zoom(self, percent: float) -> None:
        self._pending_camera_pan_delta = None
        self._camera.zoom(percent)
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()

    def frame_selected(self) -> bool:
        """Frame the current selection.

        A single selected entity is centered (camera position only, no zoom
        change -- matches historical behavior). Multiple selected entities
        are framed with a bounding-box zoom-to-fit, same as ``frame_scene``,
        since centering alone would not guarantee a spread-out selection is
        fully visible.
        """
        if self._scene is None:
            return False
        ids = self._selected_ids_set or (
            {self._target.selected_id} if self._target.selected_id else set()
        )
        if len(ids) <= 1:
            selected_id = next(iter(ids), None)
            if selected_id is None:
                return False
            entity = self._scene.find_entity(selected_id)
            transform = entity.get_component(TransformComponent) if entity else None
            framed = self._camera.frame_selected((transform.x, transform.y) if transform else None)
            if framed:
                self._pending_camera_pan_delta = None
                self._target_dirty = True
                self._grid_dirty = True
                self._notify_camera_change()
                self._redraw()
            return framed
        points = []
        for entity_id in ids:
            entity = self._scene.find_entity(entity_id)
            transform = entity.get_component(TransformComponent) if entity else None
            if transform is not None:
                points.append((transform.x, transform.y))
        return self._apply_frame_fit(points)

    def frame_scene(self) -> bool:
        """Centre and zoom the editor camera to fit all enabled entities.

        This is an explicit user command — it is the ONLY place where an
        automatic zoom-to-fit is applied.  Normal panel resize must NOT call
        this method.
        """
        if self._scene is None:
            return False
        points = [
            (transform.x, transform.y)
            for entity in self._scene.entities
            if entity.enabled and (transform := entity.get_component(TransformComponent))
        ]
        return self._apply_frame_fit(points)

    def _apply_frame_fit(self, points: list[tuple[float, float]]) -> bool:
        vw, vh = self._canvas.viewport_size()
        vw, vh = max(1, vw), max(1, vh)
        fit = compute_frame_fit(points, (vw, vh), self._camera._base_ppu)
        if fit is None:
            return False
        self._pending_camera_pan_delta = None
        center, new_zoom = fit
        self._camera.zoom_level = new_zoom
        self._camera._camera = Camera2D(
            position=center,
            viewport=(vw, vh),
            target_width=vw / (self._camera._base_ppu * new_zoom),
        )
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return True

    def _schedule_redraw(self) -> None:
        """Coalesce multiple same-tick events into one deferred redraw."""
        if not self._redraw_pending:
            self._redraw_pending = True
            self._canvas.schedule_idle(self._flush_redraw)

    def _flush_redraw(self) -> None:
        self._redraw_pending = False
        self._redraw()

    def _on_resize(self) -> None:
        width, height = self._canvas.viewport_size()
        viewport = max(1, width), max(1, height)
        self._pending_camera_pan_delta = None
        self._camera.resize(viewport)
        self._grid_dirty = True
        self._target = reproject_editor_render_target(
            self._target,
            self._scene,
            viewport=viewport,
            camera=self._camera,
            observer=self._observer,
            resolved_camera=self._resolved_runtime_camera,
        )
        self._target_dirty = False
        self._items_by_id = {item.key: item for item in self._target.items}
        self._schedule_redraw()

    def _refresh_target_if_dirty(self) -> None:
        if not self._target_dirty:
            return
        width, height = self._canvas.viewport_size()
        self._target = reproject_editor_render_target(
            self._target,
            self._scene,
            viewport=(max(1, width), max(1, height)),
            camera=self._camera if self._editor_overlays else None,
            observer=self._observer,
            resolved_camera=self._resolved_runtime_camera,
            preview_items=self._preview_render_items,
        )
        self._items_by_id = {item.key: item for item in self._target.items}
        self._target_dirty = False

    def _redraw(self) -> None:
        self._refresh_target_if_dirty()
        canvas = self._canvas
        width, height = canvas.viewport_size()
        w = width or 400
        h = height or 300

        # Screen grid lines persist across pans; only the camera axes move.
        if self._editor_overlays:
            if self._grid_dirty:
                with observe_stage(self._observer, "editor.viewport.grid"):
                    self._draw_grid(w, h)
                self._grid_dirty = False
        else:
            if self._grid_dirty:
                self._clear_grid()
                self._grid_dirty = False

        # No-scene placeholder
        if self._scene is not None and self._no_scene_text_id is not None:
            canvas.delete(self._no_scene_text_id)
            self._no_scene_text_id = None
        if self._world is not None:
            self._pixel_renderer.clear()
            self._canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")
            self._pixel_image = None
            self._draw_world(self._world)
            return
        if self._scene is None:
            self._clear_all_items()
            self._pixel_renderer.clear()
            self._canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")
            self._pixel_image = None
            if self._no_scene_text_id is None:
                self._no_scene_text_id = canvas.create_text(
                    w // 2,
                    h // 2,
                    text="No scene loaded",
                    fill=self._colors["ink_3"],
                    font=("Helvetica", 14),
                    tags="no_scene_text",
                )
            return

        camera_pan_delta = self._consume_camera_pan_delta()
        pixel_camera = (
            self._resolved_runtime_camera
            if not self._editor_overlays and self._resolved_runtime_camera is not None
            else self._camera
        )
        with observe_stage(self._observer, "editor.viewport.pixel_renderer"):
            pixel_image = self._pixel_renderer.render(
                self._target.frame,
                pixel_camera,
                max(1, int(w)),
                max(1, int(h)),
                visible_items=self._target.items,
                entity_names=self._entity_names,
            )
        runtime_pixels = pixel_image is not None
        if runtime_pixels:
            self._pixel_image = pixel_image
            canvas.itemconfigure(
                self._pixel_image_item,
                image=pixel_image,
                state="normal",
            )
        else:
            self._pixel_image = None
            canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")

        # Render items — retained model: update existing canvas items in-place.
        current_keys = {item.key for item in self._target.items}
        if camera_pan_delta is None or self._target.selected_id not in current_keys:
            self._item_layer.clear_selection()
        with observe_stage(self._observer, "editor.viewport.render_items"):
            self._item_layer.draw_items(
                self._target.items,
                modulation=self._target.frame.modulation,
                render_context=self._target.render_context,
                resolved_camera=self._resolved_runtime_camera,
                entity_names=self._entity_names,
                selected_id=self._target.selected_id,
                editor_overlays=self._editor_overlays,
                runtime_pixels=runtime_pixels,
                camera_pan_delta=camera_pan_delta,
                preview_dirty_ids=self._preview_dirty_ids,
            )

        # Collider overlays — cheap (few items), always refresh.
        # Always clear collider outlines; only redraw them in editor mode.
        with observe_stage(self._observer, "editor.viewport.colliders"):
            visible_colliders = self._target.visible_colliders(self._preview_collider_positions)
            if self._observer is not None:
                self._observer.increment(
                    "editor.viewport.colliders", "candidates", len(visible_colliders)
                )
            if self._editor_overlays:
                draw_collider_overlays(
                    canvas,
                    visible_colliders,
                    self._camera,
                    self._colors["warning"],
                    area_color=self._colors["success"],
                    entries=self._collider_overlay_entries,
                    pan_delta=camera_pan_delta,
                )
            else:
                self._clear_collider_overlays()
            if self._observer is not None:
                self._observer.set_gauge(
                    "editor.viewport.colliders",
                    "active",
                    float(len(self._collider_overlay_entries)),
                )

        # Scene camera overlay (frame/limits/follow-target) — editor mode only.
        with observe_stage(self._observer, "editor.viewport.camera_overlay"):
            if camera_pan_delta is None:
                self._clear_camera_overlay()
            if self._editor_overlays and camera_pan_delta is None:
                camera_overlay_ids: list[int] = []
                draw_camera_overlay(
                    canvas,
                    self._scene,
                    self._camera,
                    self._colors["accent"],
                    self._colors["danger"],
                    self._colors["accent_ink"],
                    created_items=camera_overlay_ids,
                )
                self._camera_overlay_ids = tuple(camera_overlay_ids)

        # Icon markers — clear when overlays are turned off, draw when on.
        if self._editor_overlays:
            viewport = (max(1, int(w)), max(1, int(h)))
            if self._marker_frame is None or not self._marker_frame.matches_camera_geometry(
                self._camera, viewport
            ):
                self._marker_frame = prepare_entity_markers(
                    self._scene,
                    self._visual_ids,
                    measure_text=getattr(canvas, "measure_text", None),
                    camera=self._camera,
                    viewport=viewport,
                )
            draw_entity_markers(
                self._canvas,
                self._colors,
                self._scene,
                self._visual_ids,
                self._selected_id,
                self._camera,
                self._marker_entries,
                prepared=self._marker_frame,
                measure_text=getattr(canvas, "measure_text", None),
                observer=self._observer,
                pan_delta=(
                    camera_pan_delta
                    if not self._preview_dirty_ids
                    else None
                ),
            )
        else:
            for entry in self._marker_entries.values():
                for item_id in entry.ids:
                    canvas.delete(item_id)
            self._marker_entries.clear()
        self._preview_dirty_ids.clear()
        if camera_pan_delta is None:
            with observe_stage(self._observer, "editor.viewport.light_gizmo"):
                self._light_gizmo = update_light_gizmo(
                    canvas,
                    self._scene,
                    self._selected_id if self._editor_overlays else None,
                    self._camera,
                    self._colors,
                    self._light_gizmo,
                )
        if camera_pan_delta is None:
            with observe_stage(self._observer, "editor.viewport.transition_overlay"):
                self._draw_transition_overlay(w, h)

    def _draw_grid(self, w: int, h: int) -> None:
        canvas = self._canvas
        c = self._colors
        if self._grid_size == (w, h) and self._grid_axis_ids is not None:
            ax, ay = self._camera.project((0.0, 0.0))
            canvas.coords(self._grid_axis_ids[0], ax, 0, ax, h)
            canvas.coords(self._grid_axis_ids[1], 0, ay, w, ay)
            return

        self._clear_grid()
        step = 40
        for gx in range(0, w, step):
            self._grid_item_ids.append(
                canvas.create_line(gx, 0, gx, h, fill=c["grid_minor"], width=1, tags="grid")
            )
        for gy in range(0, h, step):
            self._grid_item_ids.append(
                canvas.create_line(0, gy, w, gy, fill=c["grid_minor"], width=1, tags="grid")
            )
        for gx in range(0, w, step * 5):
            self._grid_item_ids.append(
                canvas.create_line(gx, 0, gx, h, fill=c["grid_major"], width=1, tags="grid")
            )
        for gy in range(0, h, step * 5):
            self._grid_item_ids.append(
                canvas.create_line(0, gy, w, gy, fill=c["grid_major"], width=1, tags="grid")
            )
        ax, ay = self._camera.project((0.0, 0.0))
        self._grid_axis_ids = (
            canvas.create_line(ax, 0, ax, h, fill=c["accent"], width=1, tags="grid"),
            canvas.create_line(0, ay, w, ay, fill=c["accent"], width=1, tags="grid"),
        )
        self._grid_item_ids.extend(self._grid_axis_ids)
        self._grid_size = (w, h)
        canvas.tag_lower("grid")

    def _clear_grid(self) -> None:
        for item_id in self._grid_item_ids:
            self._canvas.delete(item_id)
        self._grid_item_ids.clear()
        self._grid_axis_ids = None
        self._grid_size = None

    def _consume_camera_pan_delta(self) -> tuple[float, float] | None:
        delta = self._pending_camera_pan_delta
        self._pending_camera_pan_delta = (0.0, 0.0)
        if not self._editor_overlays:
            reset = getattr(self._canvas, "reset_world_group", None)
            if callable(reset):
                reset()
            return None
        if delta is None:
            reset = getattr(self._canvas, "reset_world_group", None)
            if callable(reset):
                reset()
            return None
        if delta == (0.0, 0.0):
            return None
        translate = getattr(self._canvas, "translate_world_group", None)
        if not callable(translate):
            return None
        translate(*delta)
        return delta

    def _record_camera_pan(
        self, old_origin: tuple[float, float], new_origin: tuple[float, float]
    ) -> None:
        if self._pending_camera_pan_delta is None:
            return
        previous_x, previous_y = self._pending_camera_pan_delta
        self._pending_camera_pan_delta = (
            previous_x + new_origin[0] - old_origin[0],
            previous_y + new_origin[1] - old_origin[1],
        )

    def _preview_transform_items(self, entity_ids: tuple[str, ...]) -> None:
        scene = self._scene
        if scene is None:
            return
        affected: set[str] = set()
        pending = list(entity_ids)
        while pending:
            entity_id = pending.pop()
            if entity_id in affected:
                continue
            affected.add(entity_id)
            pending.extend(child.entity_id for child in scene.children_of(entity_id))

        if self._target.frame.submissions:
            self._rerender_current_scene()
            return

        frame_items = self._target.frame
        for entity_id in affected:
            entity = scene.find_entity(entity_id)
            collider = entity.get_component(ColliderComponent) if entity is not None else None
            transform_component = (
                entity.get_component(TransformComponent) if entity is not None else None
            )
            if (
                collider is not None
                and collider.enabled
                and transform_component is not None
                and transform_component.enabled
            ):
                self._preview_collider_positions[entity_id] = (
                    transform_component.x + collider.offset[0],
                    transform_component.y + collider.offset[1],
                )
            else:
                self._preview_collider_positions.pop(entity_id, None)
            try:
                pose = scene.world_transform(entity_id)
            except (KeyError, TypeError, ValueError):
                self._preview_render_items.pop(entity_id, None)
                continue
            base_items = frame_items._items_for_key(entity_id)
            if any(item.space is RenderSpace.VIEWPORT for item in base_items):
                self._rerender_current_scene()
                return
            if base_items:
                transform = Transform(
                    position=(pose.position[0], pose.position[1], 0.0),
                    rotation=pose.rotation,
                    scale=(pose.scale[0], pose.scale[1], 1.0),
                )
                self._preview_render_items[entity_id] = tuple(
                    replace(item, transform=transform) for item in base_items
                )
            else:
                self._preview_render_items.pop(entity_id, None)
        if self._marker_frame is not None:
            self._marker_frame.update_entity_positions(affected)
        self._preview_dirty_ids.update(affected)
        self._target_dirty = True
        self._schedule_redraw()

    def _rerender_current_scene(self) -> None:
        if self._scene is None:
            return
        self.render(
            self._scene,
            self._selected_id,
            selected_ids=self._selected_ids_set,
            editor_overlays=self._editor_overlays,
            interpolator=self._interpolator,
            interpolation_fraction=self._interpolation_fraction,
            animated_players=self._animated_players,
            world_transition_alpha=self._world_transition_alpha,
            preview_lighting=self._preview_lighting,
            modulation_entity_ids=self._modulation_entity_ids,
            primary_level_entity_ids=self._primary_level_entity_ids,
            resolved_camera=self._resolved_runtime_camera,
        )

    def _pan_camera(self, x: float, y: float) -> None:
        previous_origin = self._camera.project((0.0, 0.0))
        self._camera.pan(x, y)
        self._record_camera_pan(previous_origin, self._camera.project((0.0, 0.0)))

    def _clear_collider_overlays(self) -> None:
        for entry in self._collider_overlay_entries.values():
            self._canvas.delete(entry.item_id)
        self._collider_overlay_entries.clear()

    def _clear_camera_overlay(self) -> None:
        for item_id in self._camera_overlay_ids:
            self._canvas.delete(item_id)
        self._camera_overlay_ids = ()

    def _clear_all_items(self) -> None:
        self._item_layer.clear()
        for eid in list(self._marker_entries):
            entry = self._marker_entries[eid]
            for item_id in entry.ids:
                self._canvas.delete(item_id)
        self._marker_entries.clear()
        reset_world_group = getattr(self._canvas, "reset_world_group", None)
        if callable(reset_world_group):
            reset_world_group()
        self._clear_collider_overlays()
        self._clear_camera_overlay()
        if self._no_scene_text_id is not None:
            self._canvas.delete(self._no_scene_text_id)
            self._no_scene_text_id = None
        if self._light_gizmo is not None:
            for item in self._light_gizmo.items:
                self._canvas.delete(item)
            self._light_gizmo = None

    def _notify_camera_change(self) -> None:
        if self._on_camera_change is not None:
            self._on_camera_change(self._camera.to_dict())
