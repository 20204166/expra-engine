"""Editor Viewport — Canvas-based 2D scene renderer.

This is the architectural seam for the rendering backend. The current
implementation uses a Tk Canvas as a placeholder renderer that proves:
- scene entities can have a visual representation
- selection is reflected by highlight
- resize works

The rendering backend can later be replaced with OpenGL, Vulkan, SDL,
pyglet, moderngl, etc. The seam is the ``render_scene`` method.
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, replace
from typing import Any

from expra_engine.core.camera import Camera2D
from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.canvas_effects import modulate_color
from expra_engine.runtime.rendering import (
    RenderFrame,
    RenderItem,
)
from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer
from expra_engine.ui.layout import resize_aware
from expra_engine.ui.spatial_edit import SpatialEditController, event_extends_selection
from expra_engine.ui.styles import COLORS
from expra_engine.ui.viewport_camera import (
    VIEWPORT_BASE_PPU,
    ViewportCamera,
    compute_frame_fit,
)
from expra_engine.ui.viewport_camera_overlay import draw_camera_overlay
from expra_engine.ui.viewport_markers import (
    MarkerEntry,
    draw_entity_markers,
    update_marker_selection,
)
from expra_engine.ui.viewport_overlays import draw_collider_overlays
from expra_engine.ui.viewport_render_target import (
    ColliderOutline,
    EditorRenderTarget,
    build_editor_render_target,
)

__all__ = [
    "VIEWPORT_BASE_PPU",
    "ColliderOutline",
    "EditorRenderTarget",
    "ViewportCamera",
    "ViewportPanel",
    "build_editor_render_target",
]


@dataclass
class _CanvasEntry:
    """Retained canvas item IDs for one render-item entity."""

    shape: str  # "pixels" | "rect" | "circle" | "poly" | "text"
    body: int | None  # main shape canvas item ID, absent for pixel rendering
    label: int | None = None  # name label canvas item ID


class ViewportPanel(tk.Frame):
    """Canvas-based editor viewport.

    ``on_entity_click(entity_id)`` is called when the user clicks an entity.
    """

    _ENTITY_RADIUS = 12

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        on_entity_click: Any = None,
        camera_state: dict[str, object] | None = None,
        on_camera_change: Any = None,
        resource_service: Any | None = None,
        observer: Any | None = None,
        on_transform_commit: Any = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(
            parent, bg=c["viewport_bg"], highlightbackground=c["line"], highlightthickness=1
        )

        self._on_entity_click = on_entity_click
        self._on_camera_change = on_camera_change
        self._colors = c
        self._scene: Scene | None = None
        self._selected_id: str | None = None
        self._selected_ids_set: frozenset[str] = frozenset()
        self._target = EditorRenderTarget(RenderFrame(), (), None)
        self._target_dirty = False
        self._camera = ViewportCamera()
        self._editor_overlays = True
        self._interpolator: Any | None = None
        self._interpolation_fraction = 0.0
        self._observer = observer
        self._pixel_renderer = EditorPixelRenderer(resource_service, observer=observer)
        self._pixel_image: Any | None = None
        if camera_state:
            self._camera.apply_dict(camera_state)
        self._pan_anchor: tuple[float, float] | None = None
        self._space_held = False
        self._space_pan_anchor: tuple[float, float] | None = None

        # Render-loop state
        self._redraw_pending = False  # after_idle gate to cap redraw rate
        self._grid_dirty = True  # grid/axis needs rebuild (camera moved or canvas resized)
        self._canvas_items: dict[str, _CanvasEntry] = {}  # retained visual-entity items
        self._marker_entries: dict[str, MarkerEntry] = {}  # retained icon-marker items
        self._entity_map: dict[str, Any] = {}  # built once per render() call; O(1) lookup
        self._items_by_id: dict[str, RenderItem] = {}

        # Canvas fills the frame
        self._canvas = tk.Canvas(
            self,
            bg=c["viewport_bg"],
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)
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
        )
        # <Button-1> and <ButtonPress-1> are the SAME Tk event sequence --
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
        resize_aware(self, lambda _w: self._on_resize())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
    ) -> None:
        """Redraw the viewport for ``scene``. Called on the main thread."""
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
        self._animated_players = animated_players

        if scene_changed and scene is not None:
            self._camera.apply_dict(scene.camera)
            self._grid_dirty = True
            self._clear_all_items()
            self._pixel_renderer.clear()
        if overlays_changed:
            self._grid_dirty = True

        # Build entity map once — replaces O(n²) find_entity calls in _draw_render_item.
        self._entity_map = {e.entity_id: e for e in scene.entities} if scene is not None else {}

        self._target = build_editor_render_target(
            scene,
            viewport=(max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())),
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
            interpolator=interpolator,
            interpolation_fraction=interpolation_fraction,
            animated_players=animated_players,
            observer=self._observer,
        )
        self._items_by_id = {item.key: item for item in self._target.items}
        self._target_dirty = False
        self._redraw()

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
        self._canvas.delete("selection")

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
            item = self._items_by_id.get(entity_id)
            entry = self._canvas_items.get(entity_id)
            if item is None or entry is None:
                continue
            if entry.label is not None:
                self._canvas.itemconfig(
                    entry.label,
                    fill=(
                        self._colors["accent_ink"]
                        if entity_id == selected_id
                        else self._colors["ink_3"]
                    ),
                )
            if entity_id == selected_id and self._editor_overlays:
                self._draw_selection_outline(item)

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
        self._camera.pan(x, y)
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()

    def zoom(self, percent: float) -> None:
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
        vw = max(1, self._canvas.winfo_width())
        vh = max(1, self._canvas.winfo_height())
        fit = compute_frame_fit(points, (vw, vh), self._camera._base_ppu)
        if fit is None:
            return False
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

    # ------------------------------------------------------------------
    # Internal render loop
    # ------------------------------------------------------------------

    def _schedule_redraw(self) -> None:
        """Coalesce multiple same-tick events into one redraw via after_idle."""
        if not self._redraw_pending:
            self._redraw_pending = True
            self._canvas.after_idle(self._flush_redraw)

    def _flush_redraw(self) -> None:
        self._redraw_pending = False
        self._redraw()

    def _on_resize(self) -> None:
        self._camera.resize(
            (max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height()))
        )
        self._grid_dirty = True
        self._target = build_editor_render_target(
            self._scene,
            viewport=(max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())),
            selected_id=self._selected_id,
            camera=self._camera,
            interpolator=self._interpolator,
            interpolation_fraction=self._interpolation_fraction,
            observer=self._observer,
            animated_players=getattr(self, "_animated_players", None),
        )
        self._target_dirty = False
        self._items_by_id = {item.key: item for item in self._target.items}
        self._schedule_redraw()

    def _refresh_target_if_dirty(self) -> None:
        if not self._target_dirty:
            return
        self._target = build_editor_render_target(
            self._scene,
            viewport=(max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())),
            selected_id=self._selected_id,
            camera=self._camera if self._editor_overlays else None,
            interpolator=self._interpolator,
            interpolation_fraction=self._interpolation_fraction,
            observer=self._observer,
            animated_players=getattr(self, "_animated_players", None),
        )
        self._items_by_id = {item.key: item for item in self._target.items}
        self._target_dirty = False

    def _redraw(self) -> None:
        self._refresh_target_if_dirty()
        canvas = self._canvas
        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 300

        # Grid + axis lines — only rebuilt when camera moved or canvas resized.
        # Scene-only updates (entity data changes, play-mode ticks) skip 56+ create_line calls.
        if self._editor_overlays:
            if self._grid_dirty:
                canvas.delete("grid")
                self._draw_grid(w, h)
                self._grid_dirty = False
        else:
            if self._grid_dirty:
                canvas.delete("grid")
                self._grid_dirty = False

        # No-scene placeholder
        canvas.delete("no_scene_text")
        if self._scene is None:
            self._clear_all_items()
            self._pixel_renderer.clear()
            self._canvas.itemconfigure(self._pixel_image_item, state="hidden", image="")
            self._pixel_image = None
            canvas.create_text(
                w // 2,
                h // 2,
                text="No scene loaded",
                fill=self._colors["ink_3"],
                font=("Helvetica", 14),
                tags="no_scene_text",
            )
            return

        pixel_image = self._pixel_renderer.render(
            self._target.frame,
            self._camera,
            max(1, int(w)),
            max(1, int(h)),
            self._canvas,
            entity_names={entity_id: entity.name for entity_id, entity in self._entity_map.items()},
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
        canvas.delete("selection")
        for item in self._target.items:
            self._draw_render_item(
                item,
                editor_overlays=self._editor_overlays,
                runtime_pixels=runtime_pixels,
            )
        # Remove canvas items for entities that left the scene.
        for stale in set(self._canvas_items) - current_keys:
            self._delete_canvas_entry(self._canvas_items.pop(stale))

        # Collider overlays — cheap (few items), always refresh.
        # Always clear collider outlines; only redraw them in editor mode.
        canvas.delete("collider")
        if self._editor_overlays:
            draw_collider_overlays(
                canvas,
                self._target.colliders,
                self._camera,
                self._colors["warning"],
                area_color=self._colors["success"],
            )

        # Scene camera overlay (frame/limits/follow-target) — editor mode only.
        canvas.delete("camera_overlay")
        if self._editor_overlays:
            draw_camera_overlay(
                canvas,
                self._scene,
                self._camera,
                self._colors["accent"],
                self._colors["danger"],
                self._colors["accent_ink"],
            )

        # Icon markers — clear when overlays are turned off, draw when on.
        if self._editor_overlays:
            draw_entity_markers(
                self._canvas,
                self._colors,
                self._scene,
                current_keys,
                self._selected_id,
                self._camera,
                self._marker_entries,
            )
        else:
            for eid in list(self._marker_entries):
                canvas.delete(f"entity:{eid}")
            self._marker_entries.clear()

    def _draw_grid(self, w: int, h: int) -> None:
        canvas = self._canvas
        c = self._colors
        step = 40
        for gx in range(0, w, step):
            canvas.create_line(gx, 0, gx, h, fill=c["grid_minor"], width=1, tags="grid")
        for gy in range(0, h, step):
            canvas.create_line(0, gy, w, gy, fill=c["grid_minor"], width=1, tags="grid")
        for gx in range(0, w, step * 5):
            canvas.create_line(gx, 0, gx, h, fill=c["grid_major"], width=1, tags="grid")
        for gy in range(0, h, step * 5):
            canvas.create_line(0, gy, w, gy, fill=c["grid_major"], width=1, tags="grid")
        ax, ay = self._camera.project((0.0, 0.0))
        canvas.create_line(ax, 0, ax, h, fill=c["accent"], width=1, tags="grid")
        canvas.create_line(0, ay, w, ay, fill=c["accent"], width=1, tags="grid")
        canvas.tag_lower("grid")

    def _delete_canvas_entry(self, entry: _CanvasEntry) -> None:
        if entry.body is not None:
            self._canvas.delete(entry.body)
        if entry.label is not None:
            self._canvas.delete(entry.label)

    def _clear_all_items(self) -> None:
        for entry in self._canvas_items.values():
            self._delete_canvas_entry(entry)
        self._canvas_items.clear()
        for eid in list(self._marker_entries):
            self._canvas.delete(f"entity:{eid}")
        self._marker_entries.clear()
        self._canvas.delete("collider")
        self._canvas.delete("selection")
        self._canvas.delete("camera_overlay")

    def _draw_render_item(
        self,
        item: RenderItem,
        *,
        editor_overlays: bool = True,
        runtime_pixels: bool = False,
    ) -> None:
        transform = (
            item.sprite_transform if item.primitive.kind == "sprite" else item.world_transform
        )
        ex, ey = self._camera.project((transform.position[0], transform.position[1]))
        ppu = self._camera._camera.pixel_ratio
        sx = abs(item.primitive.size[0] * transform.scale[0]) * ppu / 2
        sy = abs(item.primitive.size[1] * transform.scale[1]) * ppu / 2
        tag = f"entity:{item.key}"
        color = self._tk_color(modulate_color(item.material.color, self._target.frame.modulation))
        outline = (
            self._tk_color(modulate_color(item.material.outline, self._target.frame.modulation))
            if item.material.outline
            else color
        )

        # Determine which canvas primitive matches the current state.
        if runtime_pixels:
            new_shape = "pixels"
        elif item.material.texture_id is not None:
            # Keep the failure path explicit: the placeholder is only used
            # after EditorPixelRenderer has logged the texture error.
            new_shape = "poly" if transform.rotation or self._camera._camera.rotation else "rect"
        elif item.primitive.kind == "circle":
            new_shape = "circle"
        elif item.primitive.kind == "text":
            new_shape = "text"
        elif transform.rotation or self._camera._camera.rotation:
            new_shape = "poly"
        else:
            new_shape = "rect"

        entry = self._canvas_items.get(item.key)
        if entry is not None and entry.shape != new_shape:
            self._delete_canvas_entry(entry)
            entry = None

        # Update existing item in-place, or create a new one.
        if new_shape == "pixels":
            body_id = entry.body if entry is not None else None
        elif new_shape == "circle":
            if entry is not None:
                assert entry.body is not None
                self._canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_oval(
                    ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
                )
        elif new_shape == "text":
            text_val = item.text.text if item.text else ""
            font_val = (item.text.font, round(item.text.size)) if item.text else "TkDefaultFont"
            if entry is not None:
                assert entry.body is not None
                self._canvas.coords(entry.body, ex, ey)
                self._canvas.itemconfig(entry.body, text=text_val, fill=color, font=font_val)
                body_id = entry.body
            else:
                body_id = self._canvas.create_text(
                    ex, ey, text=text_val, fill=color, font=font_val, tags=tag
                )
        elif new_shape == "poly":
            corners = self._projected_corners(item)
            if entry is not None:
                assert entry.body is not None
                self._canvas.coords(entry.body, *corners)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_polygon(
                    *corners, fill=color, outline=outline, tags=tag
                )
        else:  # rect
            if entry is not None:
                assert entry.body is not None
                self._canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_rectangle(
                    ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
                )

        # Name label — update color/text/position in-place.
        entity = self._entity_map.get(item.key)
        label_id: int | None = None
        if entity is not None and editor_overlays:
            label_color = (
                self._colors["accent_ink"]
                if item.key == self._target.selected_id
                else self._colors["ink_3"]
            )
            if entry is not None and entry.label is not None:
                self._canvas.coords(entry.label, ex, ey + sy + 8)
                self._canvas.itemconfig(entry.label, text=entity.name, fill=label_color)
                label_id = entry.label
            else:
                label_id = self._canvas.create_text(
                    ex,
                    ey + sy + 8,
                    text=entity.name,
                    fill=label_color,
                    font=("Helvetica", 9),
                    tags=tag,
                )
        elif entry is not None and entry.label is not None:
            # Overlays turned off — remove stale label.
            self._canvas.delete(entry.label)

        self._canvas_items[item.key] = _CanvasEntry(shape=new_shape, body=body_id, label=label_id)

        if item.key == self._target.selected_id and editor_overlays:
            self._draw_selection_outline(item)

    def _draw_selection_outline(self, item: RenderItem) -> None:
        transform = (
            item.sprite_transform if item.primitive.kind == "sprite" else item.world_transform
        )
        ex, ey = self._camera.project((transform.position[0], transform.position[1]))
        ppu = self._camera._camera.pixel_ratio
        sx = abs(item.primitive.size[0] * transform.scale[0]) * ppu / 2
        sy = abs(item.primitive.size[1] * transform.scale[1]) * ppu / 2
        self._canvas.create_rectangle(
            ex - sx - 4,
            ey - sy - 4,
            ex + sx + 4,
            ey + sy + 4,
            outline=self._colors["accent"],
            width=2,
            tags="selection",
        )

    def _projected_corners(self, item: RenderItem) -> tuple[float, ...]:
        transform = (
            item.sprite_transform if item.primitive.kind == "sprite" else item.world_transform
        )
        half_width = abs(item.primitive.size[0] * transform.scale[0]) / 2
        half_height = abs(item.primitive.size[1] * transform.scale[1]) / 2
        angle = math.radians(transform.rotation)
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        points: list[float] = []
        for local_x, local_y in (
            (-half_width, -half_height),
            (-half_width, half_height),
            (half_width, half_height),
            (half_width, -half_height),
        ):
            world_x = transform.position[0] + local_x * cos_angle - local_y * sin_angle
            world_y = transform.position[1] + local_x * sin_angle + local_y * cos_angle
            projected = self._camera.project((world_x, world_y))
            points.extend(projected)
        return tuple(points)

    @staticmethod
    def _tk_color(color: Any) -> str:
        return (
            f"#{round(color.red * 255):02x}"
            f"{round(color.green * 255):02x}{round(color.blue * 255):02x}"
        )

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def _on_click(self, event: Any) -> None:
        if not self._editor_overlays:
            return
        current_tags = self._canvas.gettags("current")
        entity_tag = next((tag for tag in current_tags if tag.startswith("entity:")), None)
        if entity_tag is not None:
            self._click_entity(entity_tag.removeprefix("entity:"), event)
            return
        world = self._camera.unproject((float(event.x), float(event.y)))
        for item in reversed(self._target.items):
            transform = (
                item.sprite_transform if item.primitive.kind == "sprite" else item.world_transform
            )
            half_width = abs(item.primitive.size[0] * transform.scale[0]) / 2
            half_height = abs(item.primitive.size[1] * transform.scale[1]) / 2
            if (
                abs(world[0] - transform.position[0]) <= half_width
                and abs(world[1] - transform.position[1]) <= half_height
            ):
                self._click_entity(item.key, event)
                return
        if self._on_entity_click is not None:
            self._on_entity_click((), False)

    def _on_pan_start(self, event: Any) -> None:
        self._pan_anchor = (float(event.x), float(event.y))

    def _on_pan_motion(self, event: Any) -> None:
        if self._pan_anchor is None:
            return
        previous_x, previous_y = self._pan_anchor
        ratio = self._camera._camera.pixel_ratio or 1.0
        self._camera.pan((previous_x - event.x) / ratio, (event.y - previous_y) / ratio)
        self._pan_anchor = (float(event.x), float(event.y))
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()

    def _on_wheel(self, event: Any) -> str:
        num = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        if num == 4 or delta > 0:
            factor = 1.1
        elif num == 5 or delta < 0:
            factor = 1.0 / 1.1
        else:
            return "break"
        self._camera.zoom_at_cursor(factor, (float(event.x), float(event.y)))
        self._notify_camera_change()
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()
        return "break"

    def _kb_zoom(self, factor: float) -> str:
        vw = self._canvas.winfo_width() or 400
        vh = self._canvas.winfo_height() or 300
        self._camera.zoom_at_cursor(factor, (vw / 2.0, vh / 2.0))
        self._notify_camera_change()
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()
        return "break"

    def _frame_selected_key(self) -> str:
        self.frame_selected()
        return "break"

    def _frame_scene_key(self) -> str:
        self.frame_scene()
        return "break"

    def _on_space_down(self, event: Any) -> None:
        self._space_held = True

    def _on_space_up(self, event: Any) -> None:
        self._space_held = False
        self._space_pan_anchor = None

    def _on_lmb_press_for_pan(self, event: Any) -> None:
        if self._space_held:
            self._space_pan_anchor = (float(event.x), float(event.y))

    def _on_lmb_motion_for_pan(self, event: Any) -> None:
        if not self._space_held or self._space_pan_anchor is None:
            return
        px, py = self._space_pan_anchor
        ratio = self._camera._camera.pixel_ratio or 1.0
        self._camera.pan((px - event.x) / ratio, (event.y - py) / ratio)
        self._space_pan_anchor = (float(event.x), float(event.y))
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()

    def _rotate_camera(self, degrees: float) -> str:
        self._camera.rotate(degrees)
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _reset_camera(self) -> str:
        self._camera.reset_view()
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _notify_camera_change(self) -> None:
        if self._on_camera_change is not None:
            self._on_camera_change(self._camera.to_dict())

    def _click_entity(self, entity_id: str, event: Any) -> None:
        if self._on_entity_click:
            self._on_entity_click((entity_id,), event_extends_selection(event))
        if not self._space_held:
            self._spatial_edit.begin_drag_on_entity(entity_id, event)

    def _on_button1_press_for_selection(self, event: Any) -> None:
        """Start a box-select when the press missed every entity tag."""
        if not self._editor_overlays or self._space_held or self._spatial_edit.is_active:
            return
        current_tags = self._canvas.gettags("current")
        if any(tag.startswith("entity:") for tag in current_tags):
            return
        self._spatial_edit.begin_box_select(event)

    def _on_b1_motion_for_selection(self, event: Any) -> None:
        if self._space_held:
            return
        if self._spatial_edit.is_dragging_transform:
            self._spatial_edit.continue_drag(event)
        else:
            self._spatial_edit.continue_box_select(event)

    def _on_button1_release(self, event: Any) -> None:
        if self._spatial_edit.is_dragging_transform:
            self._spatial_edit.end_drag()
            return
        rect = self._spatial_edit.end_box_select()
        if rect is None or self._scene is None or self._on_entity_click is None:
            return
        x0, y0, x1, y1 = rect
        hits: list[str] = []
        for entity in self._scene.entities:
            transform = entity.get_component(TransformComponent)
            if transform is None:
                continue
            sx, sy = self._camera.project((transform.x, transform.y))
            if x0 <= sx <= x1 and y0 <= sy <= y1:
                hits.append(entity.entity_id)
        self._on_entity_click(tuple(hits), event_extends_selection(event))
