"""Icon markers for non-visual scene entities (camera, player, generic).

Extracted from viewport.py to keep it under the repository's 900-line hard
limit. Pure Tk Canvas drawing over a retained ``MarkerEntry`` map the caller
owns and passes in each frame; this module holds no state of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.ui.styles import editor_entity_kind

__all__ = ("ENTITY_MARKER_RADIUS", "MarkerEntry", "draw_entity_markers")

ENTITY_MARKER_RADIUS = 12


@dataclass
class MarkerEntry:
    """Retained canvas item IDs for one icon-marker entity."""

    kind: str  # "default" | "camera" | "camera_compact" | "player" | "player_compact"
    ids: list[int] = field(default_factory=list)  # all canvas IDs in draw order


def draw_entity_markers(
    canvas: Any,
    colors: dict[str, str],
    scene: Any,
    visual_ids: set[str],
    selected_id: str | None,
    camera: Any,
    entries: dict[str, MarkerEntry],
    on_click: Callable[[str, Any], None],
) -> None:
    """Draw icon markers for non-visual entities; retain bindings across frames."""
    needed: dict[str, str] = {}  # entity_id -> kind
    for entity in scene.entities:
        if not entity.enabled or entity.entity_id in visual_ids:
            continue
        transform = entity.get_component(TransformComponent)
        has_script = any(
            getattr(comp, "component_type", None) == "script" for comp in entity.components
        )
        if transform is None and has_script:
            continue
        needed[entity.entity_id] = editor_entity_kind(entity.name) or "default"

    for stale in set(entries) - set(needed):
        canvas.delete(f"entity:{stale}")
        del entries[stale]

    for entity in scene.entities:
        eid = entity.entity_id
        if eid not in needed:
            continue
        kind = needed[eid]
        transform = entity.get_component(TransformComponent)
        ex, ey = camera.project((transform.x, transform.y) if transform else (0.0, 0.0))
        is_selected = eid == selected_id
        existing = entries.get(eid)
        if existing is not None and existing.kind == kind:
            _update_marker_coords(canvas, colors, existing, ex, ey, is_selected)
        else:
            if existing is not None:
                canvas.delete(f"entity:{eid}")
            entries[eid] = _create_marker(
                canvas, colors, entity, kind, ex, ey, is_selected, on_click
            )


def _update_marker_coords(
    canvas: Any,
    colors: dict[str, str],
    entry: MarkerEntry,
    ex: float,
    ey: float,
    is_selected: bool,
) -> None:
    """Move and recolour all canvas items for an existing marker without rebinding."""
    r = ENTITY_MARKER_RADIUS
    c = colors
    fill = c["accent"] if is_selected else c["surface"]
    outline = c["accent_ink"] if is_selected else c["ink_2"]
    label_color = c["accent_ink"] if is_selected else c["ink_3"]
    ids = entry.ids

    if entry.kind == "default":
        # [rect, label]
        canvas.coords(ids[0], ex - r, ey - r, ex + r, ey + r)
        canvas.itemconfig(ids[0], fill=fill, outline=outline)
        canvas.coords(ids[1], ex, ey + r + 8)
        canvas.itemconfig(ids[1], fill=label_color)
    elif entry.kind in {"camera", "camera_compact"}:
        # camera_compact: [rect_body, oval_body, label]
        # camera:         [rect_body, oval_body, rect_top, oval_lens, label]
        marker_fill = c["camera_active"] if is_selected else c["camera"]
        canvas.coords(ids[0], ex - r, ey - r // 2, ex + r, ey + r // 2)
        canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex - r // 2, ey - r // 2, ex + r // 2, ey + r // 2)
        canvas.itemconfig(ids[1], fill=fill, outline=outline)
        if entry.kind == "camera":
            canvas.coords(ids[2], ex - r // 2, ey - r // 2 - 3, ex - r // 5, ey - r // 2)
            canvas.itemconfig(ids[2], fill=marker_fill, outline=outline)
            canvas.coords(ids[3], ex - r // 4, ey - r // 4, ex + r // 4, ey + r // 4)
            canvas.itemconfig(ids[3], fill=marker_fill, outline=outline)
            canvas.coords(ids[4], ex, ey + r + 8)
            canvas.itemconfig(ids[4], fill=label_color)
        else:
            canvas.coords(ids[2], ex, ey + r + 8)
            canvas.itemconfig(ids[2], fill=label_color)
    elif entry.kind == "player":
        # [head_oval, body_poly, left_arm, right_arm, left_leg, right_leg, label]
        marker_fill = c["player_active"] if is_selected else c["player"]
        canvas.coords(ids[0], ex - 3, ey - r - 5, ex + 3, ey - r + 1)
        canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex, ey - r + 1, ex + 6, ey + 3, ex, ey + r, ex - 6, ey + 3)
        canvas.itemconfig(ids[1], fill=marker_fill, outline=outline)
        canvas.coords(ids[2], ex - 6, ey - 1, ex - r, ey + 6)
        canvas.itemconfig(ids[2], fill=outline)
        canvas.coords(ids[3], ex + 6, ey - 1, ex + r, ey + 6)
        canvas.itemconfig(ids[3], fill=outline)
        canvas.coords(ids[4], ex - 3, ey + 8, ex - 5, ey + r + 4)
        canvas.itemconfig(ids[4], fill=outline)
        canvas.coords(ids[5], ex + 3, ey + 8, ex + 5, ey + r + 4)
        canvas.itemconfig(ids[5], fill=outline)
        canvas.coords(ids[6], ex, ey + r + 8)
        canvas.itemconfig(ids[6], fill=label_color)
    elif entry.kind == "player_compact":
        # [diamond_poly, label]
        marker_fill = c["player_active"] if is_selected else c["player"]
        canvas.coords(ids[0], ex, ey - r, ex + r, ey, ex, ey + r, ex - r, ey)
        canvas.itemconfig(ids[0], fill=marker_fill, outline=outline)
        canvas.coords(ids[1], ex, ey + r + 8)
        canvas.itemconfig(ids[1], fill=label_color)


def _create_marker(
    canvas: Any,
    colors: dict[str, str],
    entity: Any,
    kind: str,
    ex: float,
    ey: float,
    is_selected: bool,
    on_click: Callable[[str, Any], None],
) -> MarkerEntry:
    """Create fresh canvas items for an entity marker; bind click handler once."""
    r = ENTITY_MARKER_RADIUS
    c = colors
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

    ids.append(
        canvas.create_text(
            ex, ey + r + 8, text=entity.name, fill=label_color, font=("Helvetica", 9), tags=tag
        )
    )
    canvas.tag_bind(
        tag,
        "<Button-1>",
        lambda e, eid=entity.entity_id: on_click(eid, e),  # type: ignore[misc]
    )
    return MarkerEntry(kind=kind, ids=ids)
