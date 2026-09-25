"""Viewport spatial editing — move/rotate/scale drag, box-select, snap.

Bindings (chosen to avoid every key/mouse binding ``ViewportPanel`` already
uses -- q/e/r/space/f/F/Home/Control-+/-/0/KP are camera controls,
ButtonPress-2/B2-Motion are middle-drag pan):

- Plain left-drag starting ON a selected entity's body: MOVE the whole
  current selection by the world-space drag delta.
- Alt+left-drag on a selected entity: ROTATE the selection as a rigid body
  around its centroid, by the angle swept from drag-start to the pointer.
- Alt+Shift+left-drag on a selected entity: SCALE the selection uniformly
  around its centroid, by the ratio of current to start distance from it.
- Escape while dragging: abort, restore pre-drag transforms, push no
  command.
- Left-drag starting on EMPTY canvas (not Space-held, not on an entity):
  box-select -- selects every entity whose projected screen position falls
  inside the drawn rectangle on release.

Live preview mutates ``TransformComponent`` fields directly and schedules a
redraw; the whole gesture becomes exactly one undo entry (a single
``TransformEntityCommand``, or a ``CompositeCommand`` of one per entity for
a multi-selection drag) pushed on release -- see ``end_drag()``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.math_utils import round_to_closest
from expra_engine.editor.commands import Command, CompositeCommand, TransformEntityCommand

__all__ = ("SpatialEditController",)

_TransformTuple = tuple[float, float, float, float, float]

# X11 Tk event.state bits used to detect modifier keys during a drag.
_SHIFT_BIT = 0x0001
_CONTROL_BIT = 0x0004
_ALT_BIT = 0x0008


def event_extends_selection(event: Any) -> bool:
    """Return True if Shift or Control is held on this Tk event."""
    state = int(getattr(event, "state", 0) or 0)
    return bool(state & _SHIFT_BIT) or bool(state & _CONTROL_BIT)


def _read_transform(entity: Any) -> _TransformTuple | None:
    transform = entity.get_component(TransformComponent)
    if transform is None:
        return None
    return (transform.x, transform.y, transform.rotation, transform.scale_x, transform.scale_y)


def _write_transform(entity: Any, values: _TransformTuple) -> None:
    transform = entity.get_component(TransformComponent)
    if transform is None:
        return
    transform.x, transform.y, transform.rotation, transform.scale_x, transform.scale_y = values


class SpatialEditController:
    """Owns move/rotate/scale drag state and box-select for one ViewportPanel."""

    def __init__(
        self,
        *,
        camera: Any,
        canvas: Any,
        get_scene: Callable[[], Any | None],
        get_selected_ids: Callable[[], Sequence[str]],
        push_command: Callable[[Command], None],
        request_redraw: Callable[[], None],
    ) -> None:
        self._camera = camera
        self._canvas = canvas
        self._get_scene = get_scene
        self._get_selected_ids = get_selected_ids
        self._push_command = push_command
        self._request_redraw = request_redraw

        self.grid_snap_enabled = False
        self.grid_size = 1.0
        self.rotation_snap_enabled = False
        self.rotation_step_degrees = 15.0

        self._mode: str | None = None  # "move" | "rotate" | "scale" | "box_select" | None
        self._drag_start_screen: tuple[float, float] | None = None
        self._drag_last_screen: tuple[float, float] | None = None
        self._centroid: tuple[float, float] | None = None
        self._start_distance: float = 0.0
        self._start_angle: float = 0.0
        self._originals: dict[str, _TransformTuple] = {}
        self._box_select_rect_id: int | None = None

    @property
    def is_dragging_transform(self) -> bool:
        return self._mode in ("move", "rotate", "scale")

    @property
    def is_active(self) -> bool:
        """True while any gesture (drag or box-select) is in progress."""
        return self._mode is not None

    # ------------------------------------------------------------------
    # Move / rotate / scale
    # ------------------------------------------------------------------

    def begin_drag_on_entity(self, entity_id: str, event: Any) -> None:
        """Start a move/rotate/scale gesture; ``entity_id`` is the pressed entity.

        No-ops if a gesture is already in progress (keeps this deterministic
        against the rare case where both the entity's own click binding and
        a fallback hit-test both fire for the same press) or if the entity
        is not part of the current selection.
        """
        if self._mode is not None:
            return
        selected = tuple(self._get_selected_ids())
        if entity_id not in selected:
            return
        scene = self._get_scene()
        if scene is None:
            return
        originals: dict[str, _TransformTuple] = {}
        for eid in selected:
            entity = scene.find_entity(eid)
            transform = _read_transform(entity) if entity is not None else None
            if transform is not None:
                originals[eid] = transform
        if not originals:
            return
        self._originals = originals

        state = int(getattr(event, "state", 0) or 0)
        alt = bool(state & _ALT_BIT)
        shift = bool(state & _SHIFT_BIT)
        screen = (float(event.x), float(event.y))
        self._drag_start_screen = screen
        self._drag_last_screen = screen
        self._centroid = self._compute_centroid()
        if self._centroid is not None:
            world = self._camera.unproject(screen)
            dx, dy = world[0] - self._centroid[0], world[1] - self._centroid[1]
            self._start_distance = math.hypot(dx, dy)
            self._start_angle = math.atan2(dy, dx)
        self._mode = "scale" if (alt and shift) else "rotate" if alt else "move"

    def continue_drag(self, event: Any) -> None:
        if not self.is_dragging_transform:
            return
        scene = self._get_scene()
        if scene is None:
            return
        screen = (float(event.x), float(event.y))
        self._drag_last_screen = screen
        if self._mode == "move":
            self._apply_move(scene, screen)
        elif self._mode == "rotate":
            self._apply_rotate(scene, screen)
        elif self._mode == "scale":
            self._apply_scale(scene, screen)
        self._request_redraw()

    def end_drag(self) -> None:
        if not self.is_dragging_transform:
            self._reset_drag_state()
            return
        scene = self._get_scene()
        if scene is not None:
            commands: list[Command] = []
            for eid, old in self._originals.items():
                entity = scene.find_entity(eid)
                if entity is None:
                    continue
                new = _read_transform(entity)
                if new is None:
                    continue
                new = self._snap(new)
                _write_transform(entity, new)
                if new != old:
                    commands.append(TransformEntityCommand(scene, eid, old, new))
            if commands:
                command = commands[0] if len(commands) == 1 else CompositeCommand(commands)
                self._push_command(command)
        self._reset_drag_state()
        self._request_redraw()

    def cancel_drag(self) -> None:
        """Abort mid-drag (Escape): restore originals, push no command."""
        if not self.is_dragging_transform:
            self._reset_drag_state()
            return
        scene = self._get_scene()
        if scene is not None:
            for eid, old in self._originals.items():
                entity = scene.find_entity(eid)
                if entity is not None:
                    _write_transform(entity, old)
        self._reset_drag_state()
        self._request_redraw()

    # ------------------------------------------------------------------
    # Box select
    # ------------------------------------------------------------------

    def begin_box_select(self, event: Any) -> None:
        if self._mode is not None:
            return
        self._mode = "box_select"
        self._drag_start_screen = (float(event.x), float(event.y))
        self._drag_last_screen = self._drag_start_screen

    def continue_box_select(self, event: Any) -> None:
        if self._mode != "box_select" or self._drag_start_screen is None:
            return
        self._drag_last_screen = (float(event.x), float(event.y))
        x0, y0 = self._drag_start_screen
        x1, y1 = self._drag_last_screen
        if self._box_select_rect_id is None:
            self._box_select_rect_id = self._canvas.create_rectangle(
                x0, y0, x1, y1, outline="#4da6ff", dash=(3, 2), tags="box_select"
            )
        else:
            self._canvas.coords(self._box_select_rect_id, x0, y0, x1, y1)

    def end_box_select(self) -> tuple[float, float, float, float] | None:
        """Finish box-select; return the screen-space rect (x0,y0,x1,y1), or None."""
        if (
            self._mode != "box_select"
            or self._drag_start_screen is None
            or self._drag_last_screen is None
        ):
            self._reset_drag_state()
            return None
        x0, y0 = self._drag_start_screen
        x1, y1 = self._drag_last_screen
        self._reset_drag_state()
        if abs(x1 - x0) < 2 and abs(y1 - y0) < 2:
            return None
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reset_drag_state(self) -> None:
        if self._box_select_rect_id is not None:
            self._canvas.delete(self._box_select_rect_id)
            self._box_select_rect_id = None
        self._mode = None
        self._drag_start_screen = None
        self._drag_last_screen = None
        self._centroid = None
        self._originals = {}

    def _compute_centroid(self) -> tuple[float, float] | None:
        if not self._originals:
            return None
        xs = [values[0] for values in self._originals.values()]
        ys = [values[1] for values in self._originals.values()]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def _apply_move(self, scene: Any, screen: tuple[float, float]) -> None:
        if self._drag_start_screen is None:
            return
        start_world = self._camera.unproject(self._drag_start_screen)
        current_world = self._camera.unproject(screen)
        dx = current_world[0] - start_world[0]
        dy = current_world[1] - start_world[1]
        for eid, (ox, oy, orot, osx, osy) in self._originals.items():
            entity = scene.find_entity(eid)
            if entity is not None:
                _write_transform(entity, (ox + dx, oy + dy, orot, osx, osy))

    def _apply_rotate(self, scene: Any, screen: tuple[float, float]) -> None:
        if self._centroid is None:
            return
        world = self._camera.unproject(screen)
        angle = math.atan2(world[1] - self._centroid[1], world[0] - self._centroid[0])
        delta = math.degrees(angle - self._start_angle)
        cx, cy = self._centroid
        rad = math.radians(delta)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        for eid, (ox, oy, orot, osx, osy) in self._originals.items():
            entity = scene.find_entity(eid)
            if entity is None:
                continue
            rx, ry = ox - cx, oy - cy
            nx = cx + rx * cos_a - ry * sin_a
            ny = cy + rx * sin_a + ry * cos_a
            _write_transform(entity, (nx, ny, orot + delta, osx, osy))

    def _apply_scale(self, scene: Any, screen: tuple[float, float]) -> None:
        if self._centroid is None or self._start_distance <= 1e-9:
            return
        world = self._camera.unproject(screen)
        cx, cy = self._centroid
        distance = math.hypot(world[0] - cx, world[1] - cy)
        factor = max(0.01, distance / self._start_distance)
        for eid, (ox, oy, orot, osx, osy) in self._originals.items():
            entity = scene.find_entity(eid)
            if entity is None:
                continue
            nx = cx + (ox - cx) * factor
            ny = cy + (oy - cy) * factor
            _write_transform(entity, (nx, ny, orot, osx * factor, osy * factor))

    def _snap(self, values: _TransformTuple) -> _TransformTuple:
        x, y, rotation, scale_x, scale_y = values
        if self.grid_snap_enabled and self.grid_size > 0:
            x = round_to_closest(x, self.grid_size)
            y = round_to_closest(y, self.grid_size)
        if self.rotation_snap_enabled and self.rotation_step_degrees > 0:
            rotation = round_to_closest(rotation, self.rotation_step_degrees)
        return (x, y, rotation, scale_x, scale_y)
