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
from collections.abc import Iterable
from dataclasses import dataclass
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

# Pixels per world unit at zoom=1.0 on any canvas size.
# At default zoom a 1-unit entity occupies 40 px regardless of panel layout.
VIEWPORT_BASE_PPU: float = 40.0
_MIN_ZOOM: float = 0.05
_MAX_ZOOM: float = 20.0


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


class ViewportCamera:
    """Small editor camera adapter backed by the existing Camera2D contract.

    pixel_ratio is always VIEWPORT_BASE_PPU * zoom_level, independent of
    canvas size.  Resizing the canvas only changes how much of the world is
    visible — it never alters entity screen scale or camera position.
    """

    def __init__(self, viewport: tuple[int, int] = (400, 300)) -> None:
        self._viewport = (max(1, viewport[0]), max(1, viewport[1]))
        self._base_ppu: float = VIEWPORT_BASE_PPU
        self.zoom_level: float = 1.0
        vw, vh = self._viewport
        self._camera = Camera2D(viewport=(vw, vh), target_width=vw / self._base_ppu)

    @property
    def position(self) -> tuple[float, float]:
        return self._camera.position

    def pan(self, x: float, y: float) -> None:
        self._camera.position = (self.position[0] + x, self.position[1] + y)

    def zoom(self, percent: float) -> None:
        new_level = self.zoom_level * (1.0 + percent / 100.0)
        self.zoom_level = max(_MIN_ZOOM, min(_MAX_ZOOM, new_level))
        vw, vh = self._viewport
        position = self.position
        self._camera = Camera2D(
            position=position,
            viewport=(vw, vh),
            target_width=vw / (self._base_ppu * self.zoom_level),
        )

    def zoom_at_cursor(self, factor: float, cursor_screen: tuple[float, float]) -> None:
        """Zoom by ``factor`` keeping the world point under the cursor fixed.

        ``factor`` is a multiplier: 1.5 zooms in 50%, 0.5 zooms out 50%.
        Invalid factors (<=0, non-finite) are silently ignored.
        """
        if not math.isfinite(factor) or factor <= 0.0:
            return
        world_before = self._camera.translate_to_game(cursor_screen)
        new_level = max(_MIN_ZOOM, min(_MAX_ZOOM, self.zoom_level * factor))
        if abs(new_level - self.zoom_level) < 1e-9:
            return
        self.zoom_level = new_level
        vw, vh = self._viewport
        position = self.position
        self._camera = Camera2D(
            position=position,
            viewport=(vw, vh),
            target_width=vw / (self._base_ppu * self.zoom_level),
        )
        world_after = self._camera.translate_to_game(cursor_screen)
        dx = world_before[0] - world_after[0]
        dy = world_before[1] - world_after[1]
        self._camera.position = (position[0] + dx, position[1] + dy)

    def resize(self, viewport: tuple[int, int]) -> None:
        if viewport[0] <= 0 or viewport[1] <= 0:
            return
        self._viewport = (viewport[0], viewport[1])
        position = self.position
        vw, vh = self._viewport
        self._camera = Camera2D(
            position=position,
            viewport=(vw, vh),
            target_width=vw / (self._base_ppu * self.zoom_level),
        )

    def frame_selected(self, point: tuple[float, float] | None) -> bool:
        if point is None:
            return False
        self._camera.position = point
        return True

    def frame_scene(self, points: Iterable[tuple[float, float]]) -> bool:
        values = tuple(points)
        if not values:
            return False
        self._camera.position = (
            (min(point[0] for point in values) + max(point[0] for point in values)) / 2,
            (min(point[1] for point in values) + max(point[1] for point in values)) / 2,
        )
        return True

    def project(self, point: tuple[float, float]) -> tuple[float, float]:
        return self._camera.translate_to_screen(point)

    def unproject(self, point: tuple[float, float]) -> tuple[float, float]:
        return self._camera.translate_to_game(point)

    def rotate(self, degrees: float) -> None:
        self._camera.rotation += math.radians(float(degrees))

    def reset_view(self) -> None:
        self.zoom_level = 1.0
        vw, vh = self._viewport
        self._camera = Camera2D(viewport=(vw, vh), target_width=vw / self._base_ppu)

    def to_dict(self) -> dict[str, object]:
        return self._camera.to_dict()

    def apply_dict(self, values: object) -> None:
        self._camera.apply_dict(values)
        raw_zoom = self._camera.zoom
        saved_position = self.position
        saved_rotation = self._camera.rotation
        self.zoom_level = max(
            _MIN_ZOOM, min(_MAX_ZOOM, raw_zoom if math.isfinite(raw_zoom) and raw_zoom > 0 else 1.0)
        )
        vw, vh = self._viewport
        self._camera = Camera2D(
            position=saved_position,
            viewport=(vw, vh),
            target_width=vw / (self._base_ppu * self.zoom_level),
        )
        self._camera.rotation = saved_rotation


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
        self._scene = scene
        self._selected_id = selected_id
        self._editor_overlays = editor_overlays
        self._interpolator = interpolator
        self._interpolation_fraction = interpolation_fraction
        self._animated_players = animated_players
        if scene_changed and scene is not None:
            self._camera.apply_dict(scene.camera)
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
        self._notify_camera_change()
        self._redraw()

    def zoom(self, percent: float) -> None:
        self._camera.zoom(percent)
        self._notify_camera_change()
        self._redraw()

    def frame_selected(self) -> bool:
        if self._scene is None or self._target.selected_id is None:
            return False
        entity = self._scene.find_entity(self._target.selected_id)
        transform = entity.get_component(TransformComponent) if entity else None
        framed = self._camera.frame_selected((transform.x, transform.y) if transform else None)
        if framed:
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
        self._notify_camera_change()
        self._redraw()
        return True

    def _on_resize(self) -> None:
        self._camera.resize(
            (max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height()))
        )
        self._target = build_editor_render_target(
            self._scene,
            viewport=(max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())),
            selected_id=self._selected_id,
            camera=self._camera,
            interpolator=self._interpolator,
            interpolation_fraction=self._interpolation_fraction,
            animated_players=getattr(self, "_animated_players", None),
        )
        self._redraw()

    def _redraw(self) -> None:
        canvas = self._canvas
        canvas.delete("all")
        c = self._colors
        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 300
        cx, cy = w // 2, h // 2

        if self._editor_overlays:
            # Grid lines
            grid_color = c["grid_minor"]
            major_grid_color = c["grid_major"]
            step = 40
            for gx in range(0, w, step):
                canvas.create_line(gx, 0, gx, h, fill=grid_color, width=1)
            for gy in range(0, h, step):
                canvas.create_line(0, gy, w, gy, fill=grid_color, width=1)

            for gx in range(0, w, step * 5):
                canvas.create_line(gx, 0, gx, h, fill=major_grid_color, width=1)
            for gy in range(0, h, step * 5):
                canvas.create_line(0, gy, w, gy, fill=major_grid_color, width=1)

            # Axis lines
            axis_x, axis_y = self._camera.project((0.0, 0.0))
            canvas.create_line(axis_x, 0, axis_x, h, fill=c["accent"], width=1)
            canvas.create_line(0, axis_y, w, axis_y, fill=c["accent"], width=1)

        if self._scene is None:
            canvas.create_text(
                cx,
                cy,
                text="No scene loaded",
                fill=c["ink_3"],
                font=("Helvetica", 14),
            )
            return

        visual_ids = {item.key for item in self._target.items}
        for item in self._target.items:
            self._draw_render_item(item, editor_overlays=self._editor_overlays)
        if self._editor_overlays:
            self._draw_colliders()

        r = self._ENTITY_RADIUS
        if self._editor_overlays:
            for entity in self._scene.entities:
                if not entity.enabled:
                    continue
                if entity.entity_id in visual_ids:
                    continue
                transform = entity.get_component(TransformComponent)
                kind = editor_entity_kind(entity.name)
                has_script = any(
                    getattr(component, "component_type", None) == "script"
                    for component in entity.components
                )
                if transform is None and has_script:
                    continue
                ex, ey = self._camera.project(
                    (transform.x, transform.y) if transform else (0.0, 0.0)
                )

                is_selected = entity.entity_id == self._selected_id
                fill = c["accent"] if is_selected else c["surface"]
                outline = c["accent_ink"] if is_selected else c["ink_2"]

                tag = f"entity:{entity.entity_id}"
                if kind in {"camera", "camera_compact"}:
                    marker_fill = c["camera_active"] if is_selected else c["camera"]
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
                    if kind == "camera":
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
                elif kind == "player":
                    marker_fill = c["player_active"] if is_selected else c["player"]
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
                    canvas.create_line(
                        ex - 6,
                        ey - 1,
                        ex - r,
                        ey + 6,
                        fill=outline,
                        width=2,
                        tags=tag,
                    )
                    canvas.create_line(
                        ex + 6,
                        ey - 1,
                        ex + r,
                        ey + 6,
                        fill=outline,
                        width=2,
                        tags=tag,
                    )
                    canvas.create_line(
                        ex - 3,
                        ey + 8,
                        ex - 5,
                        ey + r + 4,
                        fill=outline,
                        width=2,
                        tags=tag,
                    )
                    canvas.create_line(
                        ex + 3,
                        ey + 8,
                        ex + 5,
                        ey + r + 4,
                        fill=outline,
                        width=2,
                        tags=tag,
                    )
                elif kind == "player_compact":
                    marker_fill = c["player_active"] if is_selected else c["player"]
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
                else:
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
                canvas.create_text(
                    ex,
                    ey + r + 8,
                    text=entity.name,
                    fill=c["ink_3"] if not is_selected else c["accent_ink"],
                    font=("Helvetica", 9),
                    tags=tag,
                )
                canvas.tag_bind(
                    tag,
                    "<Button-1>",
                    lambda _e, eid=entity.entity_id: self._click_entity(eid),  # type: ignore[misc]
                )

    def _draw_render_item(self, item: RenderItem, *, editor_overlays: bool = True) -> None:
        transform = (
            item.sprite_transform if item.primitive.kind == "sprite" else item.world_transform
        )
        ex, ey = self._camera.project((transform.position[0], transform.position[1]))
        sx = abs(item.primitive.size[0] * transform.scale[0]) * self._camera._camera.pixel_ratio / 2
        sy = abs(item.primitive.size[1] * transform.scale[1]) * self._camera._camera.pixel_ratio / 2
        tag = f"entity:{item.key}"
        color = self._tk_color(modulate_color(item.material.color, self._target.frame.modulation))
        outline = (
            self._tk_color(modulate_color(item.material.outline, self._target.frame.modulation))
            if item.material.outline
            else color
        )
        if item.primitive.kind == "circle":
            self._canvas.create_oval(
                ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
            )
        elif item.primitive.kind == "text":
            text = item.text.text if item.text else ""
            font = (item.text.font, round(item.text.size)) if item.text else "TkDefaultFont"
            self._canvas.create_text(ex, ey, text=text, fill=color, font=font, tags=tag)
        elif transform.rotation or self._camera._camera.rotation:
            self._canvas.create_polygon(
                *self._projected_corners(item), fill=color, outline=outline, tags=tag
            )
        else:
            self._canvas.create_rectangle(
                ex - sx, ey - sy, ex + sx, ey + sy, fill=color, outline=outline, tags=tag
            )
        if editor_overlays:
            self._canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _e, eid=item.key: self._click_entity(eid),  # type: ignore[misc]
            )
        entity = self._scene.find_entity(item.key) if self._scene is not None else None
        if entity is not None and editor_overlays:
            self._canvas.create_text(
                ex,
                ey + sy + 8,
                text=entity.name,
                fill=self._colors["accent_ink"]
                if item.key == self._target.selected_id
                else self._colors["ink_3"],
                font=("Helvetica", 9),
                tags=tag,
            )
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

    @staticmethod
    def _tk_color(color: Any) -> str:
        return f"#{round(color.red * 255):02x}{round(color.green * 255):02x}{round(color.blue * 255):02x}"

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
        self._redraw()

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
        self._redraw()
        return "break"

    def _kb_zoom(self, factor: float) -> str:
        vw = self._canvas.winfo_width() or 400
        vh = self._canvas.winfo_height() or 300
        self._camera.zoom_at_cursor(factor, (vw / 2.0, vh / 2.0))
        self._notify_camera_change()
        self._redraw()
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
        self._redraw()

    def _rotate_camera(self, degrees: float) -> str:
        self._camera.rotate(degrees)
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _reset_camera(self) -> str:
        self._camera.reset_view()
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _notify_camera_change(self) -> None:
        if self._on_camera_change is not None:
            self._on_camera_change(self._camera.to_dict())

    def _click_entity(self, entity_id: str) -> None:
        if self._on_entity_click:
            self._on_entity_click(entity_id)
