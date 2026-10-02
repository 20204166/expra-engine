"""Mouse and keyboard interaction handlers shared by editor viewports."""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.observability import observe_stage
from expra_engine.ui.spatial_edit import event_extends_selection


class ViewportInputMixin:
    """Route canvas gestures into camera and spatial-edit operations."""

    def __getattr__(self, name: str) -> Any:
        """Resolve host-owned viewport state supplied by ``ViewportCore``."""
        raise AttributeError(name)

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
            transform = item.visual_transform
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
        with observe_stage(self._observer, "editor.viewport.camera_update"):
            self._pan_camera((previous_x - event.x) / ratio, (event.y - previous_y) / ratio)
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
        self._pending_camera_pan_delta = None
        self._camera.zoom_at_cursor(factor, (float(event.x), float(event.y)))
        self._notify_camera_change()
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()
        return "break"

    def _kb_zoom(self, factor: float) -> str:
        vw, vh = self._canvas.viewport_size()
        vw = vw or 400
        vh = vh or 300
        self._pending_camera_pan_delta = None
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
        with observe_stage(self._observer, "editor.viewport.camera_update"):
            self._pan_camera((px - event.x) / ratio, (event.y - py) / ratio)
        self._space_pan_anchor = (float(event.x), float(event.y))
        self._target_dirty = True
        self._grid_dirty = True
        self._schedule_redraw()

    def _rotate_camera(self, degrees: float) -> str:
        self._pending_camera_pan_delta = None
        self._camera.rotate(degrees)
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

    def _reset_camera(self) -> str:
        self._pending_camera_pan_delta = None
        self._camera.reset_view()
        self._target_dirty = True
        self._grid_dirty = True
        self._notify_camera_change()
        self._redraw()
        return "break"

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
