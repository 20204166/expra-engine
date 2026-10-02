"""Retained Canvas projection for renderer-neutral editor render items."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from expra_engine.runtime.canvas_effects import modulate_color
from expra_engine.runtime.rendering import RenderContext, RenderItem, RenderSpace, Viewport


@dataclass
class CanvasItemEntry:
    """Canvas handles and last style for one retained RenderItem entity."""

    shape: str
    body: int | None
    label: int | None = None
    body_style: tuple[Any, ...] | None = None
    label_style: tuple[str, str] | None = None


class ViewportItemLayer:
    """Own retained canvas handles for scene-derived RenderItems."""

    def __init__(self, canvas: Any, colors: dict[str, str], camera: Any) -> None:
        self.canvas = canvas
        self.colors = colors
        self.camera = camera
        self.entries: dict[str, CanvasItemEntry] = {}
        self._selection_ids: list[int] = []

    def clear(self) -> None:
        for entry in self.entries.values():
            self._delete_entry(entry)
        self.entries.clear()
        self.clear_selection()

    def clear_selection(self) -> None:
        for item_id in self._selection_ids:
            self.canvas.delete(item_id)
        self._selection_ids.clear()

    def draw_items(
        self,
        items: tuple[RenderItem, ...],
        *,
        modulation: Any,
        render_context: RenderContext | None,
        resolved_camera: Any | None,
        entity_names: Mapping[str, str],
        selected_id: str | None,
        editor_overlays: bool,
        runtime_pixels: bool,
        camera_pan_delta: tuple[float, float] | None,
        preview_dirty_ids: set[str],
    ) -> None:
        current_keys = {item.key for item in items}
        if camera_pan_delta is None or selected_id not in current_keys:
            self.clear_selection()
        for item in items:
            self._draw_item(
                item,
                modulation=modulation,
                render_context=render_context,
                resolved_camera=resolved_camera,
                entity_names=entity_names,
                selected_id=selected_id,
                editor_overlays=editor_overlays,
                runtime_pixels=runtime_pixels,
                camera_pan_delta=camera_pan_delta,
                preview_dirty_ids=preview_dirty_ids,
            )
        for stale in set(self.entries) - current_keys:
            self._delete_entry(self.entries.pop(stale))

    def update_selection(
        self,
        previous_id: str | None,
        selected_id: str | None,
        *,
        items_by_id: Mapping[str, RenderItem],
        entity_names: Mapping[str, str],
        render_context: RenderContext | None,
        editor_overlays: bool,
    ) -> None:
        self.clear_selection()
        for entity_id in dict.fromkeys((previous_id, selected_id)):
            if entity_id is None:
                continue
            item = items_by_id.get(entity_id)
            entry = self.entries.get(entity_id)
            if item is None or entry is None:
                continue
            if entry.label is not None and editor_overlays:
                self.canvas.itemconfig(
                    entry.label,
                    fill=(
                        self.colors["accent_ink"]
                        if entity_id == selected_id
                        else self.colors["ink_3"]
                    ),
                )
            if entity_id == selected_id and editor_overlays:
                self._draw_selection_outline(item, render_context)

    def _draw_item(
        self,
        item: RenderItem,
        *,
        modulation: Any,
        render_context: RenderContext | None,
        resolved_camera: Any | None,
        entity_names: Mapping[str, str],
        selected_id: str | None,
        editor_overlays: bool,
        runtime_pixels: bool,
        camera_pan_delta: tuple[float, float] | None,
        preview_dirty_ids: set[str],
    ) -> None:
        entry = self.entries.get(item.key)
        if (
            camera_pan_delta is not None
            and editor_overlays
            and item.space is RenderSpace.WORLD
            and not runtime_pixels
            and entry is not None
            and item.key not in preview_dirty_ids
        ):
            return

        runtime_context = render_context if item.space is RenderSpace.VIEWPORT else None
        if runtime_context is None and not editor_overlays and resolved_camera is not None:
            width, height = self.canvas.viewport_size()
            runtime_context = RenderContext(
                Viewport(0, 0, max(1, width), max(1, height)), resolved_camera
            )
        if runtime_context is not None:
            transform = item.resolved_transform(runtime_context)
            ex, ey = item.project_point(runtime_context)
            ppu_x = runtime_context.viewport.width / runtime_context.camera.width
            ppu_y = runtime_context.viewport.height / runtime_context.camera.height
            screen_rotation = transform.rotation - math.degrees(runtime_context.camera.rotation)
        else:
            transform = item.visual_transform
            ex, ey = self.camera.project(transform.position[:2])
            ppu_x = ppu_y = self.camera._camera.pixel_ratio
            screen_rotation = transform.rotation - math.degrees(self.camera._camera.rotation)
        sx = abs(item.primitive.size[0] * transform.scale[0]) * ppu_x / 2
        sy = abs(item.primitive.size[1] * transform.scale[1]) * ppu_y / 2
        tag = f"entity:{item.key}"
        world_layer = item.space is RenderSpace.WORLD
        color = self._tk_color(modulate_color(item.material.color, modulation))
        outline = (
            self._tk_color(modulate_color(item.material.outline, modulation))
            if item.material.outline
            else color
        )
        text_value = item.text.text if item.text else ""
        font_value = (item.text.font, round(item.text.size)) if item.text else "default-font"

        if runtime_pixels:
            shape = "pixels"
        elif item.material.texture_id is not None:
            shape = "poly" if screen_rotation else "rect"
        elif item.primitive.kind == "circle":
            shape = "circle"
        elif item.primitive.kind == "text":
            shape = "text"
        elif screen_rotation:
            shape = "poly"
        else:
            shape = "rect"

        if entry is not None and entry.shape != shape:
            self._delete_entry(entry)
            entry = None
        body_style: tuple[Any, ...] | None = (
            (text_value, color, font_value) if shape == "text" else (color, outline)
        )
        if shape == "pixels":
            body_style = None

        if shape == "pixels":
            body_id = entry.body if entry is not None else None
        elif shape == "circle":
            if entry is not None:
                assert entry.body is not None
                self.canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                if entry.body_style != body_style:
                    self.canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self.canvas.create_oval(
                    ex - sx,
                    ey - sy,
                    ex + sx,
                    ey + sy,
                    fill=color,
                    outline=outline,
                    tags=tag,
                    world_layer=world_layer,
                )
        elif shape == "text":
            if entry is not None:
                assert entry.body is not None
                self.canvas.coords(entry.body, ex, ey)
                if entry.body_style != body_style:
                    self.canvas.itemconfig(entry.body, text=text_value, fill=color, font=font_value)
                body_id = entry.body
            else:
                body_id = self.canvas.create_text(
                    ex,
                    ey,
                    text=text_value,
                    fill=color,
                    font=font_value,
                    tags=tag,
                    world_layer=world_layer,
                )
        elif shape == "poly":
            corners = self._projected_corners(item, runtime_context)
            if entry is not None:
                assert entry.body is not None
                self.canvas.coords(entry.body, *corners)
                if entry.body_style != body_style:
                    self.canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self.canvas.create_polygon(
                    *corners, fill=color, outline=outline, tags=tag, world_layer=world_layer
                )
        else:
            if entry is not None:
                assert entry.body is not None
                self.canvas.coords(entry.body, ex - sx, ey - sy, ex + sx, ey + sy)
                if entry.body_style != body_style:
                    self.canvas.itemconfig(entry.body, fill=color, outline=outline)
                body_id = entry.body
            else:
                body_id = self.canvas.create_rectangle(
                    ex - sx,
                    ey - sy,
                    ex + sx,
                    ey + sy,
                    fill=color,
                    outline=outline,
                    tags=tag,
                    world_layer=world_layer,
                )

        entity_name = entity_names.get(item.key)
        label_id: int | None = None
        label_style: tuple[str, str] | None = None
        if entity_name is not None and editor_overlays:
            label_color = (
                self.colors["accent_ink"] if item.key == selected_id else self.colors["ink_3"]
            )
            label_style = (entity_name, label_color)
            if entry is not None and entry.label is not None:
                self.canvas.coords(entry.label, ex, ey + sy + 8)
                if entry.label_style != label_style:
                    self.canvas.itemconfig(entry.label, text=entity_name, fill=label_color)
                label_id = entry.label
            else:
                label_id = self.canvas.create_text(
                    ex,
                    ey + sy + 8,
                    text=entity_name,
                    fill=label_color,
                    font=("Helvetica", 9),
                    tags=tag,
                    world_layer=world_layer,
                )
        elif entry is not None and entry.label is not None:
            self.canvas.delete(entry.label)

        self.entries[item.key] = CanvasItemEntry(shape, body_id, label_id, body_style, label_style)
        if item.key == selected_id and editor_overlays:
            self._draw_selection_outline(item, runtime_context)

    def _draw_selection_outline(
        self, item: RenderItem, context: RenderContext | None = None
    ) -> None:
        if context is not None:
            transform = item.resolved_transform(context)
            ex, ey = context.camera.project(transform.position[:2], context.viewport)
            ppu_x = context.viewport.width / context.camera.width
            ppu_y = context.viewport.height / context.camera.height
        else:
            transform = item.visual_transform
            ex, ey = self.camera.project(transform.position[:2])
            ppu_x = ppu_y = self.camera._camera.pixel_ratio
        sx = abs(item.primitive.size[0] * transform.scale[0]) * ppu_x / 2
        sy = abs(item.primitive.size[1] * transform.scale[1]) * ppu_y / 2
        self._selection_ids.append(
            self.canvas.create_rectangle(
                ex - sx - 4,
                ey - sy - 4,
                ex + sx + 4,
                ey + sy + 4,
                outline=self.colors["accent"],
                width=2,
                tags="selection",
                world_layer=context is None,
            )
        )

    def _projected_corners(
        self, item: RenderItem, context: RenderContext | None = None
    ) -> tuple[float, ...]:
        transform = item.resolved_transform(context) if context is not None else item.visual_transform
        half_width = abs(item.primitive.size[0] * transform.scale[0]) / 2
        half_height = abs(item.primitive.size[1] * transform.scale[1]) / 2
        angle = math.radians(transform.rotation)
        cosine, sine = math.cos(angle), math.sin(angle)
        points: list[float] = []
        for local_x, local_y in (
            (-half_width, -half_height),
            (-half_width, half_height),
            (half_width, half_height),
            (half_width, -half_height),
        ):
            if context is not None:
                projected = item.project_point(context, (local_x, local_y))
            else:
                world_x = transform.position[0] + local_x * cosine - local_y * sine
                world_y = transform.position[1] + local_x * sine + local_y * cosine
                projected = self.camera.project((world_x, world_y))
            points.extend(projected)
        return tuple(points)

    def _delete_entry(self, entry: CanvasItemEntry) -> None:
        if entry.body is not None:
            self.canvas.delete(entry.body)
        if entry.label is not None:
            self.canvas.delete(entry.label)

    @staticmethod
    def _tk_color(color: Any) -> str:
        return (
            f"#{round(color.red * 255):02x}"
            f"{round(color.green * 255):02x}{round(color.blue * 255):02x}"
        )
