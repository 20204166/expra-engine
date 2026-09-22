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
from dataclasses import dataclass, field
from typing import Any

from expra_engine.core.camera import Camera2D
from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.canvas_effects import modulate_color
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderItem,
    Viewport,
)
from expra_engine.ui.layout import resize_aware
from expra_engine.ui.styles import COLORS, editor_entity_kind
from expra_engine.ui.viewport_camera import (
    _MAX_ZOOM,
    _MIN_ZOOM,
    VIEWPORT_BASE_PPU,
    ViewportCamera,
)

__all__ = [
    "VIEWPORT_BASE_PPU",
    "ColliderOutline",
    "EditorRenderTarget",
    "ViewportCamera",
    "ViewportPanel",
    "build_editor_render_target",
]


@dataclass(frozen=True)
class ColliderOutline:
    entity_id: str
    outline: dict[str, Any]
    position: tuple[float, float]


@dataclass(frozen=True)
class EditorRenderTarget:
    """Renderer-neutral preview data plus editor-only overlay inputs."""

    frame: RenderFrame
    items: tuple[RenderItem, ...]
    selected_id: str | None
    colliders: tuple[ColliderOutline, ...] = ()


@dataclass
class _CanvasEntry:
    """Retained canvas item IDs for one render-item entity."""

    shape: str  # "rect" | "circle" | "poly" | "text"
    body: int  # main shape canvas item ID
    label: int | None = None  # name label canvas item ID


@dataclass
class _MarkerEntry:
    """Retained canvas item IDs for one icon-marker entity."""

    kind: str  # "default" | "camera" | "camera_compact" | "player" | "player_compact"
    ids: list[int] = field(default_factory=list)  # all canvas IDs in draw order


def build_editor_render_target(
    scene: Scene | None,
    *,
    viewport: tuple[int, int] = (400, 300),
    selected_id: str | None = None,
    camera: Any | None = None,
    interpolator: Any | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
) -> EditorRenderTarget:
    """Extract the runtime frame once and apply editor preview clipping."""
    if scene is None:
        return EditorRenderTarget(RenderFrame(), (), None)
    frame = extract_render_frame(
        scene,
        interpolator=interpolator,
        interpolation_fraction=interpolation_fraction,
        animated_players=animated_players,
    )
    width, height = viewport
    if width <= 0 or height <= 0:
        return EditorRenderTarget(frame, (), None)
    # Use the editor camera's actual visible width so culling matches rendering.
    if camera is not None:
        cam_width = camera._camera.width
        cam_height = cam_width * height / width
    else:
        cam_width = 20.0
        cam_height = 20.0 * height / width
    preview_camera = OrthographicCamera(width=cam_width, height=cam_height)
    preview_camera.apply_dict(scene.camera)
    if camera is not None:
        preview_camera.position = camera.position
        preview_camera.rotation = camera._camera.rotation
    context = RenderContext(Viewport(0, 0, width, height), preview_camera)
    items = frame.visible_items(context)
    entity_ids = {entity.entity_id for entity in scene.entities}
    colliders: list[ColliderOutline] = []
    for entity in scene.entities:
        collider = entity.get_component(ColliderComponent)
        transform = entity.get_component(TransformComponent)
        if entity.enabled and collider is not None and collider.enabled and transform is not None:
            colliders.append(
                ColliderOutline(
                    entity.entity_id,
                    collider.editor_outline,
                    (transform.x + collider.offset[0], transform.y + collider.offset[1]),
                )
            )
    return EditorRenderTarget(
        frame, items, selected_id if selected_id in entity_ids else None, tuple(colliders)
    )


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
        self._target = EditorRenderTarget(RenderFrame(), (), None)
        self._camera = ViewportCamera()
        self._editor_overlays = True
        self._interpolator: Any | None = None
        self._interpolation_fraction = 0.0
        if camera_state:
            self._camera.apply_dict(camera_state)
        self._pan_anchor: tuple[float, float] | None = None
        self._space_held = False
        self._space_pan_anchor: tuple[float, float] | None = None

        # Render-loop state
        self._redraw_pending = False  # after_idle gate to cap redraw rate
        self._grid_dirty = True  # grid/axis needs rebuild (camera moved or canvas resized)
        self._canvas_items: dict[str, _CanvasEntry] = {}  # retained visual-entity items
        self._marker_entries: dict[str, _MarkerEntry] = {}  # retained icon-marker items
        self._entity_map: dict[str, Any] = {}  # built once per render() call; O(1) lookup

        # Canvas fills the frame
        self._canvas = tk.Canvas(
            self,
            bg=c["viewport_bg"],
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_click)
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
        self._canvas.bind("<ButtonPress-1>", self._on_lmb_press_for_pan)
        self._canvas.bind("<B1-Motion>", self._on_lmb_motion_for_pan)
        resize_aware(self, lambda _w: self._on_resize())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        scene: Scene | None,
        selected_id: str | None = None,
        *,
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
        self._editor_overlays = editor_overlays
        self._interpolator = interpolator
        self._interpolation_fraction = interpolation_fraction
        self._animated_players = animated_players

        if scene_changed and scene is not None:
            self._camera.apply_dict(scene.camera)
            self._grid_dirty = True
            self._clear_all_items()
        if overlays_changed:
            self._grid_dirty = True

        # Build entity map once — replaces O(n²) find_entity calls in _draw_render_item.
        self._entity_map = {e.entity_id: e for e in scene.entities} if scene is not None else {}

        self._target = build_editor_render_target(
            scene,
            viewport=(max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())),
            selected_id=selected_id,
            camera=self._camera,
            interpolator=interpolator,
            interpolation_fraction=interpolation_fraction,
            animated_players=animated_players,
        )
        self._redraw()

    def pan(self, x: float, y: float) -> None:
        self._camera.pan(x, y)
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()

    def zoom(self, percent: float) -> None:
        self._camera.zoom(percent)
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()

    def frame_selected(self) -> bool:
        if self._scene is None or self._target.selected_id is None:
            return False
        entity = self._scene.find_entity(self._target.selected_id)
        transform = entity.get_component(TransformComponent) if entity else None
        framed = self._camera.frame_selected((transform.x, transform.y) if transform else None)
        if framed:
            self._grid_dirty = True
            self._notify_camera_change()
            self._redraw()
        return framed

    def frame_scene(self) -> bool:
        """Centre and zoom the editor camera to fit all enabled entities.

        This is an explicit user command — it is the ONLY place where an
        automatic zoom-to-fit is applied.  Normal panel resize must NOT call
        this method.
        """
        if self._scene is None:
            return False
        points = []
        for entity in self._scene.entities:
            transform = entity.get_component(TransformComponent)
            if entity.enabled and transform:
                points.append((transform.x, transform.y))
        if not points:
            return False
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        padding = 4.0
        world_w = max(padding, max_x - min_x + padding)
        world_h = max(padding, max_y - min_y + padding)
        vw = max(1, self._canvas.winfo_width())
        vh = max(1, self._canvas.winfo_height())
        fit_ppu_w = vw / world_w
        fit_ppu_h = vh / world_h
        new_zoom = max(
            _MIN_ZOOM, min(_MAX_ZOOM, min(fit_ppu_w, fit_ppu_h) / self._camera._base_ppu * 0.9)
        )
        self._camera.zoom_level = new_zoom
        self._camera._camera = Camera2D(
            position=(center_x, center_y),
            viewport=(vw, vh),
            target_width=vw / (self._camera._base_ppu * new_zoom),
        )
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
            animated_players=getattr(self, "_animated_players", None),
        )
        self._schedule_redraw()

    def _redraw(self) -> None:
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
            canvas.create_text(
                w // 2,
                h // 2,
                text="No scene loaded",
                fill=self._colors["ink_3"],
                font=("Helvetica", 14),
                tags="no_scene_text",
            )
            return

        # Render items — retained model: update existing canvas items in-place.
        current_keys = {item.key for item in self._target.items}
        canvas.delete("selection")
        for item in self._target.items:
            self._draw_render_item(item, editor_overlays=self._editor_overlays)
        # Remove canvas items for entities that left the scene.
        for stale in set(self._canvas_items) - current_keys:
            self._delete_canvas_entry(self._canvas_items.pop(stale))

        # Collider overlays — cheap (few items), always refresh.
        if self._editor_overlays:
            canvas.delete("collider")
            self._draw_colliders()

        # Icon markers for non-visual entities — retained, binds only on creation.
        if self._editor_overlays:
            self._draw_entity_markers(current_keys)

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

    def _draw_render_item(self, item: RenderItem, *, editor_overlays: bool = True) -> None:
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
        if item.primitive.kind == "circle":
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
        if new_shape == "circle":
            if entry is not None:
                self._canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_oval(
                    ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
                )
                if editor_overlays:
                    self._canvas.tag_bind(
                        tag, "<Button-1>", lambda _e, eid=item.key: self._click_entity(eid)
                    )
        elif new_shape == "text":
            text_val = item.text.text if item.text else ""
            font_val = (item.text.font, round(item.text.size)) if item.text else "TkDefaultFont"
            if entry is not None:
                self._canvas.coords(entry.body, ex, ey)
                self._canvas.itemconfig(entry.body, text=text_val, fill=color, font=font_val)
                body_id = entry.body
            else:
                body_id = self._canvas.create_text(
                    ex, ey, text=text_val, fill=color, font=font_val, tags=tag
                )
                if editor_overlays:
                    self._canvas.tag_bind(
                        tag, "<Button-1>", lambda _e, eid=item.key: self._click_entity(eid)
                    )
        elif new_shape == "poly":
            corners = self._projected_corners(item)
            if entry is not None:
                self._canvas.coords(entry.body, *corners)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_polygon(
                    *corners, fill=color, outline=outline, tags=tag
                )
                if editor_overlays:
                    self._canvas.tag_bind(
                        tag, "<Button-1>", lambda _e, eid=item.key: self._click_entity(eid)
                    )
        else:  # rect
            if entry is not None:
                self._canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                self._canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self._canvas.create_rectangle(
                    ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
                )
                if editor_overlays:
                    self._canvas.tag_bind(
                        tag, "<Button-1>", lambda _e, eid=item.key: self._click_entity(eid)
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

        # Selection highlight — always recreated (at most 1 per frame, tag="selection").
        if item.key == self._target.selected_id and editor_overlays:
            self._canvas.create_rectangle(
                ex - sx - 4,
                ey - sy - 4,
                ex + sx + 4,
                ey + sy + 4,
                outline=self._colors["accent"],
                width=2,
                tags="selection",
            )

        self._canvas_items[item.key] = _CanvasEntry(shape=new_shape, body=body_id, label=label_id)

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

    def _draw_colliders(self) -> None:
        for collider in self._target.colliders:
            ex, ey = self._camera.project(collider.position)
            data = collider.outline
            if data["shape"] == "circle":
                radius = float(data["radius"]) * self._camera._camera.pixel_ratio
                self._canvas.create_oval(
                    ex - radius,
                    ey - radius,
                    ex + radius,
                    ey + radius,
                    outline=self._colors["warning"],
                    dash=(4, 2),
                    tags="collider",
                )
            else:
                width = float(data["width"]) * self._camera._camera.pixel_ratio / 2
                height = float(data["height"]) * self._camera._camera.pixel_ratio / 2
                self._canvas.create_rectangle(
                    ex - width,
                    ey - height,
                    ex + width,
                    ey + height,
                    outline=self._colors["warning"],
                    dash=(4, 2),
                    tags="collider",
                )

    def _draw_entity_markers(self, visual_ids: set[str]) -> None:
        """Draw icon markers for non-visual entities; retain bindings across frames."""
        if self._scene is None:
            return
        # Determine which entities need markers this frame.
        needed: dict[str, str] = {}  # entity_id -> kind
        for entity in self._scene.entities:
            if not entity.enabled or entity.entity_id in visual_ids:
                continue
            transform = entity.get_component(TransformComponent)
            has_script = any(
                getattr(comp, "component_type", None) == "script" for comp in entity.components
            )
            if transform is None and has_script:
                continue
            needed[entity.entity_id] = editor_entity_kind(entity.name)

        # Delete stale markers.
        for stale in set(self._marker_entries) - set(needed):
            self._canvas.delete(f"entity:{stale}")
            del self._marker_entries[stale]

        # Update or create each marker.
        for entity in self._scene.entities:
            eid = entity.entity_id
            if eid not in needed:
                continue
            kind = needed[eid]
            transform = entity.get_component(TransformComponent)
            ex, ey = self._camera.project((transform.x, transform.y) if transform else (0.0, 0.0))
            is_selected = eid == self._selected_id
            existing = self._marker_entries.get(eid)
            if existing is not None and existing.kind == kind:
                self._update_marker_coords(existing, entity, ex, ey, is_selected)
            else:
                if existing is not None:
                    self._canvas.delete(f"entity:{eid}")
                self._marker_entries[eid] = self._create_marker(entity, kind, ex, ey, is_selected)

    def _update_marker_coords(
        self,
        entry: _MarkerEntry,
        entity: Any,
        ex: float,
        ey: float,
        is_selected: bool,
    ) -> None:
        """Move and recolour all canvas items for an existing marker without rebinding."""
        r = self._ENTITY_RADIUS
        c = self._colors
        fill = c["accent"] if is_selected else c["surface"]
        outline = c["accent_ink"] if is_selected else c["ink_2"]
        label_color = c["accent_ink"] if is_selected else c["ink_3"]
        ids = entry.ids

        if entry.kind == "default":
            # [rect, label]
            self._canvas.coords(ids[0], ex - r, ey - r, ex + r, ey + r)
            self._canvas.itemconfig(ids[0], fill=fill, outline=outline)
            self._canvas.coords(ids[1], ex, ey + r + 8)
            self._canvas.itemconfig(ids[1], fill=label_color)
        elif entry.kind in {"camera", "camera_compact"}:
            # camera_compact: [rect_body, oval_body, label]
            # camera:         [rect_body, oval_body, rect_top, oval_lens, label]
            marker_fill = c["camera_active"] if is_selected else c["camera"]
            self._canvas.coords(ids[0], ex - r, ey - r // 2, ex + r, ey + r // 2)
            self._canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
            self._canvas.coords(ids[1], ex - r // 2, ey - r // 2, ex + r // 2, ey + r // 2)
            self._canvas.itemconfig(ids[1], fill=fill, outline=outline)
            if entry.kind == "camera":
                self._canvas.coords(ids[2], ex - r // 2, ey - r // 2 - 3, ex - r // 5, ey - r // 2)
                self._canvas.itemconfig(ids[2], fill=marker_fill, outline=outline)
                self._canvas.coords(ids[3], ex - r // 4, ey - r // 4, ex + r // 4, ey + r // 4)
                self._canvas.itemconfig(ids[3], fill=marker_fill, outline=outline)
                self._canvas.coords(ids[4], ex, ey + r + 8)
                self._canvas.itemconfig(ids[4], fill=label_color)
            else:
                self._canvas.coords(ids[2], ex, ey + r + 8)
                self._canvas.itemconfig(ids[2], fill=label_color)
        elif entry.kind == "player":
            # [head_oval, body_poly, left_arm, right_arm, left_leg, right_leg, label]
            marker_fill = c["player_active"] if is_selected else c["player"]
            self._canvas.coords(ids[0], ex - 3, ey - r - 5, ex + 3, ey - r + 1)
            self._canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
            self._canvas.coords(ids[1], ex, ey - r + 1, ex + 6, ey + 3, ex, ey + r, ex - 6, ey + 3)
            self._canvas.itemconfig(ids[1], fill=marker_fill, outline=outline)
            self._canvas.coords(ids[2], ex - 6, ey - 1, ex - r, ey + 6)
            self._canvas.itemconfig(ids[2], fill=outline)
            self._canvas.coords(ids[3], ex + 6, ey - 1, ex + r, ey + 6)
            self._canvas.itemconfig(ids[3], fill=outline)
            self._canvas.coords(ids[4], ex - 3, ey + 8, ex - 5, ey + r + 4)
            self._canvas.itemconfig(ids[4], fill=outline)
            self._canvas.coords(ids[5], ex + 3, ey + 8, ex + 5, ey + r + 4)
            self._canvas.itemconfig(ids[5], fill=outline)
            self._canvas.coords(ids[6], ex, ey + r + 8)
            self._canvas.itemconfig(ids[6], fill=label_color)
        elif entry.kind == "player_compact":
            # [diamond_poly, label]
            marker_fill = c["player_active"] if is_selected else c["player"]
            self._canvas.coords(ids[0], ex, ey - r, ex + r, ey, ex, ey + r, ex - r, ey)
            self._canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
            self._canvas.coords(ids[1], ex, ey + r + 8)
            self._canvas.itemconfig(ids[1], fill=label_color)

    def _create_marker(
        self, entity: Any, kind: str, ex: float, ey: float, is_selected: bool
    ) -> _MarkerEntry:
        """Create fresh canvas items for an entity marker; bind click handler once."""
        r = self._ENTITY_RADIUS
        c = self._colors
        fill = c["accent"] if is_selected else c["surface"]
        outline = c["accent_ink"] if is_selected else c["ink_2"]
        label_color = c["accent_ink"] if is_selected else c["ink_3"]
        tag = f"entity:{entity.entity_id}"
        canvas = self._canvas
        ids: list[int] = []

        if kind in {"camera", "camera_compact"}:
            marker_fill = c["camera_active"] if is_selected else c["camera"]
            ids.append(
                canvas.create_rectangle(
                    ex - r,
                    ey - r // 2,
                    ex + r,
                    ey + r // 2,
                    fill=marker_fill,
                    outline=outline,
                    width=2,
                    tags=tag,
                )
            )
            ids.append(
                canvas.create_oval(
                    ex - r // 2,
                    ey - r // 2,
                    ex + r // 2,
                    ey + r // 2,
                    fill=fill,
                    outline=outline,
                    width=1,
                    tags=tag,
                )
            )
            if kind == "camera":
                ids.append(
                    canvas.create_rectangle(
                        ex - r // 2,
                        ey - r // 2 - 3,
                        ex - r // 5,
                        ey - r // 2,
                        fill=marker_fill,
                        outline=outline,
                        width=1,
                        tags=tag,
                    )
                )
                ids.append(
                    canvas.create_oval(
                        ex - r // 4,
                        ey - r // 4,
                        ex + r // 4,
                        ey + r // 4,
                        fill=marker_fill,
                        outline=outline,
                        width=1,
                        tags=tag,
                    )
                )
        elif kind == "player":
            marker_fill = c["player_active"] if is_selected else c["player"]
            ids.append(
                canvas.create_oval(
                    ex - 3,
                    ey - r - 5,
                    ex + 3,
                    ey - r + 1,
                    fill=marker_fill,
                    outline=outline,
                    width=1,
                    tags=tag,
                )
            )
            ids.append(
                canvas.create_polygon(
                    ex,
                    ey - r + 1,
                    ex + 6,
                    ey + 3,
                    ex,
                    ey + r,
                    ex - 6,
                    ey + 3,
                    fill=marker_fill,
                    outline=outline,
                    width=2,
                    tags=tag,
                )
            )
            ids.append(
                canvas.create_line(ex - 6, ey - 1, ex - r, ey + 6, fill=outline, width=2, tags=tag)
            )
            ids.append(
                canvas.create_line(ex + 6, ey - 1, ex + r, ey + 6, fill=outline, width=2, tags=tag)
            )
            ids.append(
                canvas.create_line(
                    ex - 3, ey + 8, ex - 5, ey + r + 4, fill=outline, width=2, tags=tag
                )
            )
            ids.append(
                canvas.create_line(
                    ex + 3, ey + 8, ex + 5, ey + r + 4, fill=outline, width=2, tags=tag
                )
            )
        elif kind == "player_compact":
            marker_fill = c["player_active"] if is_selected else c["player"]
            ids.append(
                canvas.create_polygon(
                    ex,
                    ey - r,
                    ex + r,
                    ey,
                    ex,
                    ey + r,
                    ex - r,
                    ey,
                    fill=marker_fill,
                    outline=outline,
                    width=2,
                    tags=tag,
                )
            )
        else:  # default
            ids.append(
                canvas.create_rectangle(
                    ex - r,
                    ey - r,
                    ex + r,
                    ey + r,
                    fill=fill,
                    outline=outline,
                    width=2,
                    tags=tag,
                )
            )

        ids.append(
            canvas.create_text(
                ex,
                ey + r + 8,
                text=entity.name,
                fill=label_color,
                font=("Helvetica", 9),
                tags=tag,
            )
        )
        canvas.tag_bind(
            tag,
            "<Button-1>",
            lambda _e, eid=entity.entity_id: self._click_entity(eid),  # type: ignore[misc]
        )
        return _MarkerEntry(kind=kind, ids=ids)

    @staticmethod
    def _tk_color(color: Any) -> str:
        return f"#{round(color.red * 255):02x}{round(color.green * 255):02x}{round(color.blue * 255):02x}"

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def _on_click(self, event: Any) -> None:
        if not self._editor_overlays:
            return
        current_tags = self._canvas.gettags("current")
        if any(tag.startswith("entity:") for tag in current_tags):
            return
        world = self._camera.unproject((float(event.x), float(event.y)))
        for item in reversed(self._target.items):
            transform = item.world_transform
            half_width = abs(item.primitive.size[0] * transform.scale[0]) / 2
            half_height = abs(item.primitive.size[1] * transform.scale[1]) / 2
            if (
                abs(world[0] - transform.position[0]) <= half_width
                and abs(world[1] - transform.position[1]) <= half_height
            ):
                self._click_entity(item.key)
                return
        if self._on_entity_click is not None:
            self._on_entity_click(None)

    def _on_pan_start(self, event: Any) -> None:
        self._pan_anchor = (float(event.x), float(event.y))

    def _on_pan_motion(self, event: Any) -> None:
        if self._pan_anchor is None:
            return
        previous_x, previous_y = self._pan_anchor
        ratio = self._camera._camera.pixel_ratio or 1.0
        self._camera.pan((previous_x - event.x) / ratio, (event.y - previous_y) / ratio)
        self._pan_anchor = (float(event.x), float(event.y))
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
        self._grid_dirty = True
        self._schedule_redraw()
        return "break"

    def _kb_zoom(self, factor: float) -> str:
        vw = self._canvas.winfo_width() or 400
        vh = self._canvas.winfo_height() or 300
        self._camera.zoom_at_cursor(factor, (vw / 2.0, vh / 2.0))
        self._notify_camera_change()
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
        self._grid_dirty = True
        self._schedule_redraw()

    def _rotate_camera(self, degrees: float) -> str:
        self._camera.rotate(degrees)
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _reset_camera(self) -> str:
        self._camera.reset_view()
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _notify_camera_change(self) -> None:
        if self._on_camera_change is not None:
            self._on_camera_change(self._camera.to_dict())

    def _click_entity(self, entity_id: str) -> None:
        if self._on_entity_click:
            self._on_entity_click(entity_id)
