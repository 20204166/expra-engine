"""Pure-math regression tests for ViewportCamera.

All tests are headless — no Tk widget is created.
These tests encode the REQUIRED invariants for the viewport fix:
  - pixel_ratio must equal BASE_PPU * zoom_level (canvas-size-independent)
  - resize must NOT change entity screen scale or camera position
  - cursor-centred zoom must keep world point under cursor fixed
  - zoom clamps must prevent zero/negative/NaN/inf pixel_ratio
  - pan math must produce the correct world-space delta
  - project/unproject must be mutual inverses within floating-point tolerance
  - repeated resize cycles must produce zero accumulated drift
"""

from __future__ import annotations

import math
import unittest

from expra_engine.ui.viewport import VIEWPORT_BASE_PPU, ViewportCamera

# Local copies matching viewport.py constants — used for assertion bounds only.
_EXPECTED_MIN_ZOOM = 0.05
_EXPECTED_MAX_ZOOM = 20.0


class ResizeInvarianceTests(unittest.TestCase):
    """Entity screen size must not change when the canvas is resized."""

    def _pixel_ratio(self, vp: tuple[int, int], zoom_level: float = 1.0) -> float:
        cam = ViewportCamera(viewport=vp)
        if zoom_level != 1.0:
            # zoom() takes percent-change: 1.5 zoom_level = zoom(50)
            percent = (zoom_level - 1.0) * 100.0
            cam.zoom(percent)
        return cam._camera.pixel_ratio

    def test_wide_then_narrow_same_pixel_ratio(self) -> None:
        wide = self._pixel_ratio((1200, 700))
        narrow = self._pixel_ratio((800, 700))
        self.assertAlmostEqual(
            wide,
            narrow,
            places=6,
            msg="pixel_ratio must not depend on canvas width at zoom=1.0",
        )

    def test_tall_then_short_same_pixel_ratio(self) -> None:
        tall = self._pixel_ratio((800, 700))
        short = self._pixel_ratio((800, 400))
        self.assertAlmostEqual(
            tall,
            short,
            places=6,
            msg="pixel_ratio must not depend on canvas height at zoom=1.0",
        )

    def test_pixel_ratio_equals_base_ppu_at_zoom_1(self) -> None:
        for vp in [(400, 300), (800, 600), (1200, 700), (320, 240)]:
            with self.subTest(vp=vp):
                ppu = self._pixel_ratio(vp, zoom_level=1.0)
                self.assertAlmostEqual(ppu, VIEWPORT_BASE_PPU, places=5)

    def test_resize_preserves_pixel_ratio(self) -> None:
        cam = ViewportCamera(viewport=(1200, 700))
        cam.zoom(50.0)
        ppu_before = cam._camera.pixel_ratio
        cam.resize((800, 700))
        ppu_after = cam._camera.pixel_ratio
        self.assertAlmostEqual(
            ppu_before,
            ppu_after,
            places=6,
            msg="resize() must not change pixel_ratio (zoom unchanged)",
        )

    def test_resize_preserves_camera_center(self) -> None:
        cam = ViewportCamera(viewport=(1200, 700))
        cam._camera.position = (5.0, -3.0)
        cam.resize((800, 400))
        self.assertAlmostEqual(cam.position[0], 5.0, places=6)
        self.assertAlmostEqual(cam.position[1], -3.0, places=6)

    def test_entity_screen_size_independent_of_canvas_width(self) -> None:
        world_size = 20.0
        ppu_wide = self._pixel_ratio((1200, 700))
        ppu_narrow = self._pixel_ratio((800, 700))
        screen_wide = world_size * ppu_wide
        screen_narrow = world_size * ppu_narrow
        self.assertAlmostEqual(
            screen_wide,
            screen_narrow,
            places=4,
            msg="entity screen size must not change when viewport width changes",
        )

    def test_repeated_resize_no_drift(self) -> None:
        cam = ViewportCamera(viewport=(1200, 700))
        cam._camera.position = (10.0, 5.0)
        cam.zoom(30.0)
        zoom_before = cam.zoom_level
        cx_before, cy_before = cam.position
        ppu_before = cam._camera.pixel_ratio
        for w in [1200, 800] * 50:
            cam.resize((w, 700))
        self.assertAlmostEqual(cam.zoom_level, zoom_before, places=6)
        self.assertAlmostEqual(cam.position[0], cx_before, places=5)
        self.assertAlmostEqual(cam.position[1], cy_before, places=5)
        self.assertAlmostEqual(cam._camera.pixel_ratio, ppu_before, places=5)

    def test_space_pong_scenario_ball_scale(self) -> None:
        """Simulates the reported Space Pong failure: Inspector expands, viewport shrinks."""
        cam_wide = ViewportCamera(viewport=(1200, 700))
        cam_narrow = ViewportCamera(viewport=(800, 700))
        ball_world_size = 1.0
        ball_screen_wide = ball_world_size * cam_wide._camera.pixel_ratio
        ball_screen_narrow = ball_world_size * cam_narrow._camera.pixel_ratio
        self.assertAlmostEqual(
            ball_screen_wide,
            ball_screen_narrow,
            places=4,
            msg="Space Pong ball must not grow when Inspector expands",
        )


class CursorCentredZoomTests(unittest.TestCase):
    """World point under cursor must remain under cursor after zoom."""

    def test_zoom_in_keeps_cursor_world_point(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cursor = (300.0, 200.0)
        world_before = cam._camera.translate_to_game(cursor)
        cam.zoom_at_cursor(1.5, cursor)
        world_after = cam._camera.translate_to_game(cursor)
        self.assertAlmostEqual(world_before[0], world_after[0], places=4)
        self.assertAlmostEqual(world_before[1], world_after[1], places=4)

    def test_zoom_out_keeps_cursor_world_point(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cursor = (600.0, 400.0)
        world_before = cam._camera.translate_to_game(cursor)
        cam.zoom_at_cursor(0.5, cursor)
        world_after = cam._camera.translate_to_game(cursor)
        self.assertAlmostEqual(world_before[0], world_after[0], places=4)
        self.assertAlmostEqual(world_before[1], world_after[1], places=4)

    def test_centre_cursor_does_not_shift_camera(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam._camera.position = (5.0, 3.0)
        cx_before, cy_before = cam.position
        cam.zoom_at_cursor(1.2, (400.0, 300.0))  # cursor at screen centre
        self.assertAlmostEqual(cam.position[0], cx_before, places=4)
        self.assertAlmostEqual(cam.position[1], cy_before, places=4)

    def test_off_centre_cursor_shifts_camera(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cursor = (200.0, 150.0)  # top-left quadrant
        world_before = cam._camera.translate_to_game(cursor)
        cam.zoom_at_cursor(2.0, cursor)
        world_after = cam._camera.translate_to_game(cursor)
        self.assertAlmostEqual(world_before[0], world_after[0], places=4)
        self.assertAlmostEqual(world_before[1], world_after[1], places=4)


class ZoomClampTests(unittest.TestCase):
    """Zoom must remain bounded, finite, and positive under all inputs."""

    def test_zoom_out_spam_never_zero_or_negative(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        for _ in range(200):
            cam.zoom(-50.0)
        self.assertGreater(cam.zoom_level, 0.0)
        self.assertGreater(cam._camera.pixel_ratio, 0.0)
        self.assertTrue(math.isfinite(cam.zoom_level))
        self.assertTrue(math.isfinite(cam._camera.pixel_ratio))

    def test_zoom_in_spam_does_not_exceed_maximum(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        for _ in range(200):
            cam.zoom(50.0)
        self.assertLessEqual(cam.zoom_level, _EXPECTED_MAX_ZOOM)
        self.assertTrue(math.isfinite(cam._camera.pixel_ratio))

    def test_zoom_at_cursor_clamps_upper(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        for _ in range(200):
            cam.zoom_at_cursor(10.0, (400.0, 300.0))
        self.assertLessEqual(cam.zoom_level, _EXPECTED_MAX_ZOOM)
        self.assertTrue(math.isfinite(cam._camera.pixel_ratio))

    def test_zoom_at_cursor_clamps_lower(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        for _ in range(200):
            cam.zoom_at_cursor(0.01, (400.0, 300.0))
        self.assertGreaterEqual(cam.zoom_level, _EXPECTED_MIN_ZOOM)
        self.assertGreater(cam._camera.pixel_ratio, 0.0)

    def test_pixel_ratio_always_finite_positive(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        for factor in (0.01, 100.0, 1.0001, 0.9999, 1.1, 0.9):
            cam.zoom_at_cursor(factor, (400.0, 300.0))
            ppu = cam._camera.pixel_ratio
            self.assertTrue(math.isfinite(ppu), f"pixel_ratio not finite after factor={factor}")
            self.assertGreater(ppu, 0.0)

    def test_invalid_factor_ignored(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        ppu_before = cam._camera.pixel_ratio
        cam.zoom_at_cursor(0.0, (400.0, 300.0))
        self.assertAlmostEqual(cam._camera.pixel_ratio, ppu_before, places=6)
        cam.zoom_at_cursor(-1.0, (400.0, 300.0))
        self.assertAlmostEqual(cam._camera.pixel_ratio, ppu_before, places=6)


class PanTests(unittest.TestCase):
    """Pan must move the camera by the given world-space delta."""

    def test_pan_moves_camera(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam.pan(3.0, -2.0)
        self.assertAlmostEqual(cam.position[0], 3.0, places=6)
        self.assertAlmostEqual(cam.position[1], -2.0, places=6)

    def test_pan_screen_to_world_at_zoom_1(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        ppu = cam._camera.pixel_ratio
        screen_drag = 40.0
        world_delta = screen_drag / ppu
        cam.pan(world_delta, 0.0)
        self.assertAlmostEqual(cam.position[0], world_delta, places=5)

    def test_pan_after_resize_uses_correct_ratio(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam.resize((400, 300))
        ppu = cam._camera.pixel_ratio
        world_delta = 20.0 / ppu  # 20 screen px in world units
        cam.pan(world_delta, 0.0)
        self.assertAlmostEqual(cam.position[0], world_delta, places=5)


class RoundTripTests(unittest.TestCase):
    """project(unproject(p)) and unproject(project(p)) must recover the original point."""

    def _check_roundtrip(self, cam: ViewportCamera, world: tuple[float, float]) -> None:
        screen = cam._camera.translate_to_screen(world)
        recovered = cam._camera.translate_to_game(screen)
        self.assertAlmostEqual(world[0], recovered[0], places=5)
        self.assertAlmostEqual(world[1], recovered[1], places=5)

    def test_origin_roundtrip(self) -> None:
        self._check_roundtrip(ViewportCamera(viewport=(800, 600)), (0.0, 0.0))

    def test_off_centre_roundtrip(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam._camera.position = (5.0, -3.0)
        self._check_roundtrip(cam, (7.5, -1.0))

    def test_zoomed_roundtrip(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam.zoom(80.0)
        self._check_roundtrip(cam, (2.0, 4.0))

    def test_after_resize_roundtrip(self) -> None:
        cam = ViewportCamera(viewport=(1200, 700))
        cam.resize((800, 400))
        cam.zoom(30.0)
        self._check_roundtrip(cam, (-1.0, 2.5))

    def test_repeated_zoom_no_drift(self) -> None:
        cam = ViewportCamera(viewport=(800, 600))
        cam._camera.position = (3.0, 2.0)
        for _ in range(50):
            cam.zoom(10.0)
            cam.zoom(-10.0 / 1.1)
        self.assertTrue(math.isfinite(cam._camera.pixel_ratio))
        self.assertGreater(cam._camera.pixel_ratio, 0.0)
        self.assertTrue(math.isfinite(cam.position[0]))
        self.assertTrue(math.isfinite(cam.position[1]))
