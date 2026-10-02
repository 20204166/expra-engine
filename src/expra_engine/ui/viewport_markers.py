"""Icon markers for non-visual scene entities (camera, player, generic).

Pure canvas drawing over a retained ``MarkerEntry`` map the caller
owns and passes in each frame; this module holds no state of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.core.spatial_index import SpatialIndex2D
from expra_engine.observability import ObservabilityWatcher, observe_stage
from expra_engine.runtime.level_anchor import LevelAnchorComponent
from expra_engine.ui.styles import editor_entity_kind

__all__ = (
    "ENTITY_MARKER_RADIUS",
    "EntityMarkerFrame",
    "MarkerEntry",
    "draw_entity_markers",
    "prepare_entity_markers",
)

ENTITY_MARKER_RADIUS = 12
_MARKER_FONT = ("Helvetica", 9)


@dataclass(frozen=True)
class EntityMarker:
    entity: Any
    kind: str
    transform: TransformComponent | None
    anchor: LevelAnchorComponent | None
    position: tuple[float, float]
    screen_bounds_offset: tuple[float, float, float, float]
    world_bounds: tuple[float, float, float, float]


@dataclass
class EntityMarkerFrame:
    """Scene-lifetime marker metadata plus a reusable world-position index."""

    markers: list[EntityMarker]
    index: SpatialIndex2D[int]
    camera_geometry: tuple[float, float, float, int, int] | None
    ordinal_by_entity_id: dict[str, int]

    def visible_candidates(
        self, camera: Any, viewport: tuple[int, int] | None
    ) -> tuple[EntityMarker, ...]:
        if viewport is None:
            return tuple(self.markers)
        width, height = viewport
        if width <= 0 or height <= 0 or not self.markers:
            return ()
        if not self.matches_camera_geometry(camera, viewport):
            return tuple(self.markers)
        screen_corners = ((0, 0), (width, 0), (width, height), (0, height))
        world_corners = tuple(camera.unproject(point) for point in screen_corners)
        world_bounds = (
            min(point[0] for point in world_corners),
            min(point[1] for point in world_corners),
            max(point[0] for point in world_corners),
            max(point[1] for point in world_corners),
        )
        return tuple(self.markers[index] for index in self.index.query(world_bounds))

    def update_entity_positions(self, entity_ids: Iterable[str]) -> None:
        """Dirty-update only marker index entries whose transforms changed."""
        for entity_id in entity_ids:
            ordinal = self.ordinal_by_entity_id.get(entity_id)
            if ordinal is None:
                continue
            marker = self.markers[ordinal]
            transform = marker.transform
            position = (transform.x, transform.y) if transform is not None else (0.0, 0.0)
            dx = position[0] - marker.position[0]
            dy = position[1] - marker.position[1]
            left, top, right, bottom = marker.world_bounds
            bounds = (left + dx, top + dy, right + dx, bottom + dy)
            self.index.update(ordinal, bounds)
            self.markers[ordinal] = replace(
                marker, position=position, world_bounds=bounds
            )

    def matches_camera_geometry(self, camera: Any, viewport: tuple[int, int]) -> bool:
        geometry = (
            camera._camera.width,
            camera._camera.height,
            camera._camera.rotation,
            viewport[0],
            viewport[1],
        )
        return self.camera_geometry == geometry


@dataclass
class MarkerEntry:
    """Retained canvas item IDs for one icon-marker entity."""

    kind: str  # "default" | "camera" | "camera_compact" | "player" | "player_compact"
    ids: list[int] = field(default_factory=list)  # all canvas IDs in draw order
    screen_position: tuple[float, float] = (0.0, 0.0)
    base_fill: str | None = None
    style_key: tuple[tuple[tuple[str, str], ...], bool] | None = None
    label_text: str | None = None
    bounds_offset: tuple[float, float, float, float] | None = None
    anchor: LevelAnchorComponent | None = None


def prepare_entity_markers(
    scene: Any,
    visual_ids: Container[str],
    *,
    measure_text: Callable[[str, tuple[str, int]], tuple[float, float]] | None = None,
    camera: Any | None = None,
    viewport: tuple[int, int] | None = None,
) -> EntityMarkerFrame:
    """Build immutable marker candidates once for a scene/render-frame lifetime."""
    markers: list[EntityMarker] = []
    entries: list[tuple[int, tuple[float, float, float, float]]] = []
    ordinal_by_entity_id: dict[str, int] = {}
    camera_geometry = None
    world_corner_offsets: tuple[tuple[float, float], ...] | None = None
    if camera is not None and viewport is not None:
        camera_geometry = (
            camera._camera.width,
            camera._camera.height,
            camera._camera.rotation,
            viewport[0],
            viewport[1],
        )
        origin = camera.unproject((0.0, 0.0))
        world_corner_offsets = tuple(
            (camera.unproject(point)[0] - origin[0], camera.unproject(point)[1] - origin[1])
            for point in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        )
    for entity in scene.entities:
        anchor = entity.get_component(LevelAnchorComponent)
        if not entity.enabled or (entity.entity_id in visual_ids and anchor is None):
            continue
        transform = entity.get_component(TransformComponent)
        if transform is None and any(
            getattr(component, "component_type", None) == "script"
            for component in entity.components
        ):
            continue
        kind = "level_anchor" if anchor is not None else editor_entity_kind(entity.name) or "default"
        position = (transform.x, transform.y) if transform is not None else (0.0, 0.0)
        label = _marker_label(entity, kind, anchor)
        if measure_text is None:
            lines = label.splitlines() or [""]
            text_width = max(map(len, lines), default=0) * 18.0
            text_height = len(lines) * 20.0
        else:
            text_width, text_height = measure_text(label, _MARKER_FONT)
        left = -max(float(ENTITY_MARKER_RADIUS), text_width * 0.5 + 2.0)
        top = -17.0
        right = max(float(ENTITY_MARKER_RADIUS), text_width * 0.5 + 2.0)
        bottom = max(16.0, ENTITY_MARKER_RADIUS + 8.0 + text_height * 0.5 + 2.0)
        ordinal = len(markers)
        if world_corner_offsets is None:
            bounds = (position[0], position[1], position[0], position[1])
        else:
            screen_offsets = ((left, top), (right, top), (right, bottom), (left, bottom))
            world_offsets = tuple(
                (
                    screen_x * world_corner_offsets[1][0]
                    + screen_y * world_corner_offsets[3][0],
                    screen_x * world_corner_offsets[1][1]
                    + screen_y * world_corner_offsets[3][1],
                )
                for screen_x, screen_y in screen_offsets
            )
            bounds = (
                position[0] + min(point[0] for point in world_offsets),
                position[1] + min(point[1] for point in world_offsets),
                position[0] + max(point[0] for point in world_offsets),
                position[1] + max(point[1] for point in world_offsets),
            )
        markers.append(
            EntityMarker(entity, kind, transform, anchor, position, (left, top, right, bottom), bounds)
        )
        ordinal_by_entity_id[entity.entity_id] = ordinal
        entries.append((ordinal, bounds))
    return EntityMarkerFrame(
        markers,
        SpatialIndex2D(entries),
        camera_geometry,
        ordinal_by_entity_id,
    )


def draw_entity_markers(
    canvas: Any,
    colors: dict[str, str],
    scene: Any,
    visual_ids: Container[str],
    selected_id: str | None,
    camera: Any,
    entries: dict[str, MarkerEntry],
    *,
    prepared: EntityMarkerFrame | None = None,
    measure_text: Callable[[str, tuple[str, int]], tuple[float, float]] | None = None,
    observer: ObservabilityWatcher | None = None,
    pan_delta: tuple[float, float] | None = None,
) -> None:
    """Draw icon markers for non-visual entities; retain bindings across frames."""
    marker_frame = prepared or prepare_entity_markers(scene, visual_ids, measure_text=measure_text)
    palette_key = tuple(sorted(colors.items()))
    viewport_size = cast(Any, getattr(canvas, "viewport_size", None))
    viewport = cast(tuple[int, int], viewport_size()) if callable(viewport_size) else None
    with observe_stage(observer, "editor.viewport.marker_query"):
        marker_items = marker_frame.visible_candidates(camera, viewport)
    candidate_ids = {marker.entity.entity_id for marker in marker_items}
    removed_count = 0
    for stale in set(entries) - candidate_ids:
        _delete_marker_entry(canvas, entries, stale)
        removed_count += 1

    created_count = 0
    updated_count = 0
    shifted_count = 0
    with observe_stage(observer, "editor.viewport.marker_qt_updates"):
        existing_markers: list[EntityMarker] = []
        new_markers: list[EntityMarker] = []
        for marker in marker_items:
            (existing_markers if marker.entity.entity_id in entries else new_markers).append(marker)

        if pan_delta is not None:
            dx, dy = pan_delta
            for marker in existing_markers:
                eid = marker.entity.entity_id
                entry = entries[eid]
                ex = entry.screen_position[0] + dx
                ey = entry.screen_position[1] + dy
                if viewport is not None and not _screen_bounds_intersect(
                    marker.screen_bounds_offset, ex, ey, viewport
                ):
                    _delete_marker_entry(canvas, entries, eid)
                    removed_count += 1
                else:
                    entry.screen_position = (ex, ey)
                    shifted_count += 1

        projected_new: tuple[tuple[float, float], ...]
        if new_markers:
            with observe_stage(observer, "editor.viewport.marker_projection"):
                projected_new = camera.project_many(marker.position for marker in new_markers)
        else:
            projected_new = ()
        for marker, (ex, ey) in zip(new_markers, projected_new, strict=True):
            entity = marker.entity
            eid = entity.entity_id
            kind = marker.kind
            anchor = marker.anchor
            if viewport is not None and not _screen_bounds_intersect(
                marker.screen_bounds_offset, ex, ey, viewport
            ):
                if eid in entries:
                    _delete_marker_entry(canvas, entries, eid)
                    removed_count += 1
                continue
            is_selected = eid == selected_id
            existing = entries.get(eid)
            if existing is not None and existing.kind == kind:
                _update_marker_coords(
                    canvas,
                    colors,
                    existing,
                    entity,
                    ex,
                    ey,
                    is_selected,
                    palette_key=palette_key,
                    viewport=viewport,
                    anchor=anchor,
                )
                updated_count += 1
            else:
                if existing is not None:
                    _delete_marker_entry(canvas, entries, eid)
                    removed_count += 1
                entries[eid] = _create_marker(
                    canvas,
                    colors,
                    entity,
                    kind,
                    ex,
                    ey,
                    is_selected,
                    palette_key=palette_key,
                    anchor=anchor,
                )
                created_count += 1
        if pan_delta is None:
            projected_existing: tuple[tuple[float, float], ...]
            if existing_markers:
                with observe_stage(observer, "editor.viewport.marker_projection"):
                    projected_existing = camera.project_many(
                        marker.position for marker in existing_markers
                    )
            else:
                projected_existing = ()
            for marker, (ex, ey) in zip(existing_markers, projected_existing, strict=True):
                entity = marker.entity
                eid = entity.entity_id
                kind = marker.kind
                anchor = marker.anchor
                if viewport is not None and not _screen_bounds_intersect(
                    marker.screen_bounds_offset, ex, ey, viewport
                ):
                    _delete_marker_entry(canvas, entries, eid)
                    removed_count += 1
                    continue
                entry = entries[eid]
                _update_marker_coords(
                    canvas,
                    colors,
                    entry,
                    entity,
                    ex,
                    ey,
                    eid == selected_id,
                    palette_key=palette_key,
                    viewport=viewport,
                    anchor=anchor,
                )
                updated_count += 1
    if observer is not None:
        observer.increment("editor.viewport.markers", "total_markers", len(marker_frame.markers))
        observer.increment("editor.viewport.markers", "candidates", len(marker_items))
        observer.increment("editor.viewport.markers", "created", created_count)
        observer.increment("editor.viewport.markers", "updated", updated_count)
        observer.increment("editor.viewport.markers", "shifted", shifted_count)
        observer.increment("editor.viewport.markers", "removed", removed_count)
        observer.set_gauge("editor.viewport.markers", "active", float(len(entries)))


def _delete_marker_entry(canvas: Any, entries: dict[str, MarkerEntry], entity_id: str) -> None:
    entry = entries.pop(entity_id, None)
    if entry is not None:
        for item_id in entry.ids:
            canvas.delete(item_id)


def _marker_style_key(
    colors: dict[str, str],
    is_selected: bool,
    palette_key: tuple[tuple[str, str], ...] | None = None,
) -> tuple[tuple[tuple[str, str], ...], bool]:
    return (tuple(sorted(colors.items())) if palette_key is None else palette_key), is_selected


def _update_marker_coords(
    canvas: Any,
    colors: dict[str, str],
    entry: MarkerEntry,
    entity: Any,
    ex: float,
    ey: float,
    is_selected: bool,
    *,
    palette_key: tuple[tuple[str, str], ...] | None = None,
    viewport: tuple[int, int] | None = None,
    anchor: LevelAnchorComponent | None = None,
) -> None:
    """Move and recolour all canvas items for an existing marker without rebinding."""
    r = ENTITY_MARKER_RADIUS
    c = colors
    fill = c["accent"] if is_selected else entry.base_fill or c["surface"]
    outline = c["accent_ink"] if is_selected else c["ink_2"]
    label_color = c["accent_ink"] if is_selected else c["ink_3"]
    ids = entry.ids
    style_key = _marker_style_key(colors, is_selected, palette_key)
    restyle = entry.style_key != style_key
    label_text = (
        _marker_label(entity, entry.kind, anchor or entry.anchor)
        if entity is not None and entry.kind in {"default", "level_anchor"}
        else entry.label_text
    )
    relabel = label_text is not None and label_text != entry.label_text
    if not relabel and not restyle and entry.bounds_offset is not None and viewport is not None:
        width, height = viewport
        left, top, right, bottom = entry.bounds_offset
        old_x, old_y = entry.screen_position
        current_bounds = (old_x + left, old_y + top, old_x + right, old_y + bottom)
        dx, dy = ex - old_x, ey - old_y
        projected_bounds = (
            current_bounds[0] + dx,
            current_bounds[1] + dy,
            current_bounds[2] + dx,
            current_bounds[3] + dy,
        )
        if _outside_viewport(current_bounds, width, height) and _outside_viewport(
            projected_bounds, width, height
        ):
            return

    if entry.kind in {"default", "level_anchor"}:
        # [rect, label]
        canvas.coords(ids[0], ex - r, ey - r, ex + r, ey + r)
        if restyle:
            canvas.itemconfig(ids[0], fill=fill, outline=outline)
        canvas.coords(ids[1], ex, ey + r + 8)
        label_options: dict[str, Any] = {}
        if relabel:
            label_options["text"] = label_text
        if restyle:
            label_options["fill"] = label_color
        if label_options:
            canvas.itemconfig(ids[1], **label_options)
    elif entry.kind in {"camera", "camera_compact"}:
        # camera_compact: [rect_body, oval_body, label]
        # camera:         [rect_body, oval_body, rect_top, oval_lens, label]
        marker_fill = c["camera_active"] if is_selected else c["camera"]
        canvas.coords(ids[0], ex - r, ey - r // 2, ex + r, ey + r // 2)
        if restyle:
            canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex - r // 2, ey - r // 2, ex + r // 2, ey + r // 2)
        if restyle:
            canvas.itemconfig(ids[1], fill=fill, outline=outline)
        if entry.kind == "camera":
            canvas.coords(ids[2], ex - r // 2, ey - r // 2 - 3, ex - r // 5, ey - r // 2)
            if restyle:
                canvas.itemconfig(ids[2], fill=marker_fill, outline=outline)
            canvas.coords(ids[3], ex - r // 4, ey - r // 4, ex + r // 4, ey + r // 4)
            if restyle:
                canvas.itemconfig(ids[3], fill=marker_fill, outline=outline)
            canvas.coords(ids[4], ex, ey + r + 8)
            if restyle:
                canvas.itemconfig(ids[4], fill=label_color)
        else:
            canvas.coords(ids[2], ex, ey + r + 8)
            if restyle:
                canvas.itemconfig(ids[2], fill=label_color)
    elif entry.kind == "player":
        # [head_oval, body_poly, left_arm, right_arm, left_leg, right_leg, label]
        marker_fill = c["player_active"] if is_selected else c["player"]
        canvas.coords(ids[0], ex - 3, ey - r - 5, ex + 3, ey - r + 1)
        if restyle:
            canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex, ey - r + 1, ex + 6, ey + 3, ex, ey + r, ex - 6, ey + 3)
        if restyle:
            canvas.itemconfig(ids[1], fill=marker_fill, outline=outline)
        canvas.coords(ids[2], ex - 6, ey - 1, ex - r, ey + 6)
        if restyle:
            canvas.itemconfig(ids[2], fill=outline)
        canvas.coords(ids[3], ex + 6, ey - 1, ex + r, ey + 6)
        if restyle:
            canvas.itemconfig(ids[3], fill=outline)
        canvas.coords(ids[4], ex - 3, ey + 8, ex - 5, ey + r + 4)
        if restyle:
            canvas.itemconfig(ids[4], fill=outline)
        canvas.coords(ids[5], ex + 3, ey + 8, ex + 5, ey + r + 4)
        if restyle:
            canvas.itemconfig(ids[5], fill=outline)
        canvas.coords(ids[6], ex, ey + r + 8)
        if restyle:
            canvas.itemconfig(ids[6], fill=label_color)

    elif entry.kind == "player_compact":
        # [diamond_poly, label]
        marker_fill = c["player_active"] if is_selected else c["player"]
        canvas.coords(ids[0], ex, ey - r, ex + r, ey, ex, ey + r, ex - r, ey)
        if restyle:
            canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex, ey + r + 8)
        if restyle:
            canvas.itemconfig(ids[1], fill=label_color)

    entry.screen_position = (ex, ey)
    entry.style_key = style_key
    if entity is not None and entry.kind in {"default", "level_anchor"}:
        entry.label_text = label_text
        entry.bounds_offset = _item_bounds_offset(canvas, ids, ex, ey)
    entry.anchor = anchor or entry.anchor


def _create_marker(
    canvas: Any,
    colors: dict[str, str],
    entity: Any,
    kind: str,
    ex: float,
    ey: float,
    is_selected: bool,
    *,
    palette_key: tuple[tuple[str, str], ...] | None = None,
    anchor: LevelAnchorComponent | None = None,
) -> MarkerEntry:
    """Create fresh canvas items for an entity marker; bind click handler once."""
    r = ENTITY_MARKER_RADIUS
    c = colors
    anchor = anchor or entity.get_component(LevelAnchorComponent)
    base_fill = None
    if kind == "level_anchor" and anchor is not None:
        fill = c["success"] if anchor.kind.value == "entrance" else c["warning"]
        if anchor.kind.value == "both":
            fill = c["accent"]
        base_fill = fill
        if is_selected:
            fill = c["accent"]
    else:
        fill = c["accent"] if is_selected else c["surface"]
    outline = c["accent_ink"] if is_selected else c["ink_2"]
    label_color = c["accent_ink"] if is_selected else c["ink_3"]
    tag = (f"entity:{entity.entity_id}", "editor_marker")
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
                world_layer=True,
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
                world_layer=True,
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
                    world_layer=True,
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
                    world_layer=True,
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
                world_layer=True,
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
                world_layer=True,
            )
        )
        ids.append(
            canvas.create_line(
                ex - 6, ey - 1, ex - r, ey + 6, fill=outline, width=2, tags=tag, world_layer=True
            )
        )
        ids.append(
            canvas.create_line(
                ex + 6, ey - 1, ex + r, ey + 6, fill=outline, width=2, tags=tag, world_layer=True
            )
        )
        ids.append(
            canvas.create_line(
                ex - 3, ey + 8, ex - 5, ey + r + 4, fill=outline, width=2, tags=tag, world_layer=True
            )
        )
        ids.append(
            canvas.create_line(
                ex + 3, ey + 8, ex + 5, ey + r + 4, fill=outline, width=2, tags=tag, world_layer=True
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
                world_layer=True,
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
                world_layer=True,
            )
        )

    label_text = _marker_label(entity, kind, anchor)
    ids.append(
        canvas.create_text(
            ex,
            ey + r + 8,
            text=label_text,
            fill=label_color,
            font=("Helvetica", 9),
            tags=tag,
            world_layer=True,
        )
    )
    return MarkerEntry(
        kind=kind,
        ids=ids,
        screen_position=(ex, ey),
        base_fill=base_fill,
        style_key=_marker_style_key(colors, is_selected, palette_key),
        label_text=label_text,
        bounds_offset=_item_bounds_offset(canvas, ids, ex, ey),
        anchor=anchor,
    )


def _item_bounds_offset(
    canvas: Any, item_ids: list[int], x: float, y: float
) -> tuple[float, float, float, float] | None:
    bbox = cast(Any, getattr(canvas, "bbox", None))
    if not callable(bbox):
        return None
    bounds = cast(tuple[int, int, int, int] | None, bbox(*item_ids))
    if bounds is None:
        return None
    return (bounds[0] - x, bounds[1] - y, bounds[2] - x, bounds[3] - y)


def _outside_viewport(
    bounds: tuple[float, float, float, float], width: int, height: int
) -> bool:
    left, top, right, bottom = bounds
    # One pixel of slack covers the canvas adapter's integer bounding-box rounding.
    return right < -1.0 or left > width + 1.0 or bottom < -1.0 or top > height + 1.0


def _screen_bounds_intersect(
    offset: tuple[float, float, float, float],
    x: float,
    y: float,
    viewport: tuple[int, int],
) -> bool:
    left, top, right, bottom = offset
    width, height = viewport
    return x + right >= 0.0 and x + left <= width and y + bottom >= 0.0 and y + top <= height


def update_marker_selection(
    canvas: Any,
    colors: dict[str, str],
    entry: MarkerEntry,
    is_selected: bool,
) -> None:
    """Update one retained marker's colors without scanning scene entities."""
    _update_marker_coords(
        canvas,
        colors,
        entry,
        None,
        entry.screen_position[0],
        entry.screen_position[1],
        is_selected,
    )


def _marker_label(
    entity: Any, kind: str, anchor: LevelAnchorComponent | None = None
) -> str:
    if kind != "level_anchor" or entity is None:
        return entity.name if entity is not None else ""
    anchor = anchor or entity.get_component(LevelAnchorComponent)
    if anchor is None:
        return entity.name
    width, height = anchor.size
    return (
        f"{entity.name}\n{anchor.anchor_id} · {anchor.kind.value}\n"
        f"{width:g} x {height:g}"
    )
