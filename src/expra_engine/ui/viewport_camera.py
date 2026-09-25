"""Editor viewport camera — stable-scale adapter over Camera2D.

Extracted from viewport.py to keep both modules under the 900-line budget.
Public API is re-exported from expra_engine.ui.viewport for backwards
compatibility.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from expra_engine.core.camera import Camera2D

__all__ = (
    "VIEWPORT_BASE_PPU",
    "ViewportCamera",
    "compute_frame_fit",
)

# Pixels per world unit at zoom=1.0 on any canvas size.
# At default zoom a 1-unit entity occupies 40 px regardless of panel layout.
VIEWPORT_BASE_PPU: float = 40.0
_MIN_ZOOM: float = 0.05
_MAX_ZOOM: float = 20.0


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
        saved_position = self.position
        saved_rotation = self._camera.rotation
        vw, vh = self._viewport
        # Derive zoom_level from the *effective width* Camera2D.apply_dict just
        # applied, not from Camera2D.zoom directly -- setting "width" (as saved
        # scene cameras do) never touches Camera2D._zoom, so reading .zoom here
        # silently discarded any persisted "width" and fell back to the fixed
        # VIEWPORT_BASE_PPU scale regardless of what the scene actually saved.
        effective_width = self._camera.width
        raw_zoom = (
            vw / (self._base_ppu * effective_width)
            if math.isfinite(effective_width) and effective_width > 0
            else 1.0
        )
        self.zoom_level = max(
            _MIN_ZOOM,
            min(_MAX_ZOOM, raw_zoom if math.isfinite(raw_zoom) and raw_zoom > 0 else 1.0),
        )
        self._camera = Camera2D(
            position=saved_position,
            viewport=(vw, vh),
            target_width=vw / (self._base_ppu * self.zoom_level),
        )
        self._camera.rotation = saved_rotation


def compute_frame_fit(
    points: list[tuple[float, float]],
    viewport_size: tuple[int, int],
    base_ppu: float,
    *,
    min_zoom: float = _MIN_ZOOM,
    max_zoom: float = _MAX_ZOOM,
    padding: float = 4.0,
) -> tuple[tuple[float, float], float] | None:
    """Return ``(center, zoom_level)`` that fits every point in the viewport.

    Shared by ``ViewportPanel.frame_scene()`` (all enabled entities) and
    ``frame_selected()`` (just the current selection, when more than one
    entity is selected) so the bounding-box/zoom-fit math is written once.
    Returns ``None`` for an empty ``points``.
    """
    if not points:
        return None
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    world_w = max(padding, max_x - min_x + padding)
    world_h = max(padding, max_y - min_y + padding)
    vw, vh = viewport_size
    fit_ppu_w = vw / world_w
    fit_ppu_h = vh / world_h
    zoom_level = max(min_zoom, min(max_zoom, min(fit_ppu_w, fit_ppu_h) / base_ppu * 0.9))
    return center, zoom_level
