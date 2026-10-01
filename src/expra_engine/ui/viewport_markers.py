"""Icon markers for non-visual scene entities (camera, player, generic).

Pure canvas drawing over a retained ``MarkerEntry`` map the caller
owns and passes in each frame; this module holds no state of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.runtime.level_anchor import LevelAnchorComponent
from expra_engine.ui.styles import editor_entity_kind

__all__ = ("ENTITY_MARKER_RADIUS", "MarkerEntry", "draw_entity_markers")

ENTITY_MARKER_RADIUS = 12


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


def draw_entity_markers(
    canvas: Any,
    colors: dict[str, str],
    scene: Any,
    visual_ids: set[str],
    selected_id: str | None,
    camera: Any,
    entries: dict[str, MarkerEntry],
) -> None:
    """Draw icon markers for non-visual entities; retain bindings across frames."""
    needed: dict[str, tuple[Any, str, Any, LevelAnchorComponent | None]] = {}
    palette_key = tuple(sorted(colors.items()))
    viewport_size = cast(Any, getattr(canvas, "viewport_size", None))
    viewport = cast(tuple[int, int], viewport_size()) if callable(viewport_size) else None
    for entity in scene.entities:
        anchor = entity.get_component(LevelAnchorComponent)
        if not entity.enabled or (entity.entity_id in visual_ids and anchor is None):
            continue
        transform = entity.get_component(TransformComponent)
        if transform is None and any(
            getattr(comp, "component_type", None) == "script" for comp in entity.components
        ):
            continue
        needed[entity.entity_id] = (
            entity,
            "level_anchor" if anchor is not None else editor_entity_kind(entity.name) or "default",
            transform,
            anchor,
        )

    for stale in set(entries) - set(needed):
        canvas.delete(f"entity:{stale}")
        del entries[stale]

    for eid, (entity, kind, transform, anchor) in needed.items():
        ex, ey = camera.project((transform.x, transform.y) if transform else (0.0, 0.0))
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
        else:
            if existing is not None:
                canvas.delete(f"entity:{eid}")
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
    tag = f"entity:{entity.entity_id}"
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
            canvas.create_line(ex - 3, ey + 8, ex - 5, ey + r + 4, fill=outline, width=2, tags=tag)
        )
        ids.append(
            canvas.create_line(ex + 3, ey + 8, ex + 5, ey + r + 4, fill=outline, width=2, tags=tag)
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

    label_text = _marker_label(entity, kind, anchor)
    ids.append(
        canvas.create_text(
            ex,
            ey + r + 8,
            text=label_text,
            fill=label_color,
            font=("Helvetica", 9),
            tags=tag,
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
