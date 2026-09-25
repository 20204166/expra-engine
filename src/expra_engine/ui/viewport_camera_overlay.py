"""Editor-only visualization of the scene's own configured camera.

Distinct from the editor's free-roaming pan/zoom authoring camera
(``ViewportCamera``) -- this draws where the game's ACTUAL camera would
frame, projected through the editor's camera so placement is correct
regardless of how the author has panned/zoomed the edit view.
"""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene.camera import Camera2D

__all__ = ("draw_camera_overlay",)


def draw_camera_overlay(
    canvas: Any,
    scene: Any,
    editor_camera: Any,
    frame_color: str,
    limit_color: str,
    target_color: str,
) -> None:
    """Draw the scene's configured camera frame/limits/follow-target, if any."""
    if scene is None or not scene.camera:
        return
    probe = Camera2D(target_width=10.0)
    try:
        probe.apply_dict(scene.camera)
    except (TypeError, ValueError):
        return

    cx, cy = probe.position
    half_w, half_h = probe.width / 2.0, probe.height / 2.0
    screen_corners: list[float] = []
    for point in (
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    ):
        screen_corners.extend(editor_camera.project(point))
    canvas.create_polygon(
        *screen_corners,
        outline=frame_color,
        fill="",
        dash=(6, 3),
        width=2,
        tags="camera_overlay",
    )

    if probe.limit_enabled:
        lx0, ly0 = editor_camera.project((probe.limit_left, probe.limit_bottom))
        lx1, ly1 = editor_camera.project((probe.limit_right, probe.limit_top))
        canvas.create_rectangle(
            lx0, ly0, lx1, ly1, outline=limit_color, dash=(2, 4), tags="camera_overlay"
        )

    target_entity_id = scene.camera.target_entity_id
    if target_entity_id:
        target_entity = scene.find_entity(target_entity_id)
        transform = target_entity.get_component(TransformComponent) if target_entity else None
        if transform is not None:
            tx, ty = editor_camera.project((transform.x, transform.y))
            fx, fy = editor_camera.project((cx, cy))
            canvas.create_line(
                fx, fy, tx, ty, fill=target_color, dash=(3, 3), tags="camera_overlay"
            )
