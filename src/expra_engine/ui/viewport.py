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

import tkinter as tk
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.ui.layout import resize_aware
from expra_engine.ui.styles import COLORS, editor_entity_kind


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
    ) -> None:
        c = colors or COLORS
        super().__init__(
            parent, bg=c["viewport_bg"], highlightbackground=c["line"], highlightthickness=1
        )

        self._on_entity_click = on_entity_click
        self._colors = c
        self._scene: Scene | None = None
        self._selected_id: str | None = None

        # Canvas fills the frame
        self._canvas = tk.Canvas(
            self,
            bg=c["viewport_bg"],
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_click)
        resize_aware(self, lambda _w: self._redraw())

    def render(self, scene: Scene | None, selected_id: str | None = None) -> None:
        """Redraw the viewport for ``scene``. Called on the main thread."""
        self._scene = scene
        self._selected_id = selected_id
        self._redraw()

    def _redraw(self) -> None:
        canvas = self._canvas
        canvas.delete("all")
        c = self._colors
        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 300
        cx, cy = w // 2, h // 2

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
        canvas.create_line(cx, 0, cx, h, fill=c["accent"], width=1)
        canvas.create_line(0, cy, w, cy, fill=c["accent"], width=1)

        if self._scene is None:
            canvas.create_text(
                cx,
                cy,
                text="No scene loaded",
                fill=c["ink_3"],
                font=("Helvetica", 14),
            )
            return

        r = self._ENTITY_RADIUS
        for entity in self._scene.entities:
            if not entity.enabled:
                continue
            transform = entity.get_component(TransformComponent)
            ex = cx + (transform.x if transform else 0)
            ey = cy - (transform.y if transform else 0)

            is_selected = entity.entity_id == self._selected_id
            fill = c["accent"] if is_selected else c["surface"]
            outline = c["accent_ink"] if is_selected else c["ink_2"]

            tag = f"entity:{entity.entity_id}"
            kind = editor_entity_kind(entity.name)
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

    def _on_click(self, event: Any) -> None:
        pass

    def _click_entity(self, entity_id: str) -> None:
        if self._on_entity_click:
            self._on_entity_click(entity_id)
