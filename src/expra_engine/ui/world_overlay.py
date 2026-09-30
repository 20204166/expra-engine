"""World authoring and transition overlays drawn on the editor Canvas."""

from __future__ import annotations

from expra_engine.core.world import LevelDescriptor, World

__all__ = ("WorldOverlayMixin",)


def _descriptor_center(descriptor: LevelDescriptor) -> tuple[float, float]:
    if descriptor.bounds is None:
        return descriptor.origin
    x, y, width, height = descriptor.bounds
    return (x + width / 2.0, y + height / 2.0)


class WorldOverlayMixin:
    """Canvas drawing for World descriptors, connections, and FADE presentation."""

    def _draw_transition_overlay(self, width: int, height: int) -> None:
        canvas = self._canvas
        canvas.delete("world_transition_overlay")
        alpha = self._world_transition_alpha
        if not self._editor_overlays and alpha > 0.0:
            stipple = None if alpha >= 0.9 else "gray75" if alpha >= 0.7 else "gray50" if alpha >= 0.4 else "gray25"
            canvas.create_rectangle(
                0,
                0,
                width,
                height,
                fill="#000000",
                stipple=stipple or "",
                outline="",
                tags="world_transition_overlay",
            )
            canvas.tag_raise("world_transition_overlay")

    def _draw_world(self, world: World) -> None:
        canvas = self._canvas
        canvas.delete("world")
        self._world_style_items.clear()
        levels = {descriptor.instance_id: descriptor for descriptor in world.levels}
        for descriptor in world.levels:
            self._draw_world_level(world, descriptor)
        for connection in world.connections:
            source = levels[connection.source_level_id]
            destination = levels[connection.destination_level_id]
            source_point = _descriptor_center(source)
            destination_point = _descriptor_center(destination)
            sx, sy = self._camera.project(source_point)
            dx, dy = self._camera.project(destination_point)
            tag = f"connection:{connection.connection_id}"
            color = self._colors["accent"] if tag == self._selected_id else self._colors["ink_3"]
            line = canvas.create_line(
                sx,
                sy,
                dx,
                dy,
                fill=color,
                width=2 if tag == self._selected_id else 1,
                arrow="last",
                tags=("world", tag, f"world:{tag}"),
            )
            self._track_world_item(tag, line, "connection-line")
            label = (
                f"{connection.source_anchor_id} → {connection.destination_anchor_id}"
                f" · {connection.transition.value}"
            )
            label_item = canvas.create_text(
                (sx + dx) / 2,
                (sy + dy) / 2 - 10,
                text=label,
                fill=self._colors["ink_2"],
                font=("default-font", 8),
                tags=("world", tag, f"world:{tag}"),
            )
            self._track_world_item(tag, label_item, "connection-label")
            self._bind_world_selection(tag)
        canvas.tag_raise("world")
        self._world_drawn = True

    def _draw_world_level(self, world: World, descriptor: LevelDescriptor) -> None:
        canvas = self._canvas
        tag = f"level:{descriptor.instance_id}"
        selected = tag == self._selected_id
        color = self._colors["accent"] if selected else self._colors["ink_2"]
        if descriptor.bounds is not None:
            x, y, width, height = descriptor.bounds
            left, top = self._camera.project((x, y + height))
            right, bottom = self._camera.project((x + width, y))
            outline = canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline=color,
                width=2 if selected else 1,
                fill=self._colors["panel_bg"],
                stipple="gray50",
                tags=("world", tag, f"world:{tag}"),
            )
            self._track_world_item(tag, outline, "level-outline")
        origin_x, origin_y = self._camera.project(descriptor.origin)
        origin_item = canvas.create_oval(
            origin_x - 4,
            origin_y - 4,
            origin_x + 4,
            origin_y + 4,
            fill=color,
            outline=color,
            tags=("world", tag, f"world:{tag}"),
        )
        self._track_world_item(tag, origin_item, "level-origin")
        title = descriptor.instance_id
        if descriptor.instance_id == world.initial_level_id:
            title = f"★ {title}"
            initial_item = canvas.create_text(
                origin_x,
                origin_y,
                text="★",
                fill=self._colors["success"],
                tags=("world", f"world:initial:{descriptor.instance_id}"),
            )
            self._track_world_item(tag, initial_item, "level-initial")
        label_item = canvas.create_text(
            origin_x + 8,
            origin_y - 12,
            text=title,
            anchor="sw",
            fill=color,
            font=("default-font", 9, "bold"),
            tags=("world", f"world:{tag}"),
        )
        self._track_world_item(tag, label_item, "level-label")
        self._bind_world_selection(tag)

    def _track_world_item(self, identifier: str, item_id: int, kind: str) -> None:
        self._world_style_items.setdefault(identifier, []).append((item_id, kind))

    def _restyle_world_items(self, identifier: str, *, selected: bool) -> None:
        color = (
            self._colors["accent"]
            if selected
            else self._colors["ink_3"]
            if identifier.startswith("connection:")
            else self._colors["ink_2"]
        )
        for item_id, kind in self._world_style_items.get(identifier, ()):
            if kind == "level-outline":
                self._canvas.itemconfigure(item_id, outline=color, width=2 if selected else 1)
            elif kind == "level-origin":
                self._canvas.itemconfigure(item_id, fill=color, outline=color)
            elif kind in {"level-label", "connection-label"}:
                self._canvas.itemconfigure(item_id, fill=color)
            elif kind == "connection-line":
                self._canvas.itemconfigure(item_id, fill=color, width=2 if selected else 1)

    def _bind_world_selection(self, tag: str) -> None:
        if self._on_entity_click is not None:
            self._canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, identifier=tag: self._on_entity_click((identifier,), False)
                or "break",
            )
