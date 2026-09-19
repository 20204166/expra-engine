"""Tests for Camera2D — world/screen coordinate math.

Edge cases adapted from ppb/tests/test_camera.py (PursuedPyBear,
Artistic License 2.0). Translated to Expra's Camera2D API (no ppb_vector,
no SDL, plain float tuples).

Tests cover:
  - creation with target_width / target_height
  - pixel_ratio calculation
  - width/height coupled via aspect ratio
  - position movement
  - viewport edge properties (left/right/top/bottom/corners)
  - point_is_visible (inclusive boundary)
  - translate_to_screen / translate_to_game (forward and inverse)
  - round-trip: game → screen → game
  - round-trip: screen → game → screen
  - invalid point type raises TypeError
  - invalid dimensions raise ValueError
  - setting both dimensions simultaneously raises ValueError
"""

import unittest
from math import isclose

from expra_engine.core.camera import Camera2D


class TestCamera2DCreation(unittest.TestCase):
    def _cam(self) -> Camera2D:
        return Camera2D(viewport=(800, 600), target_width=10.0)

    def test_initial_pixel_ratio(self) -> None:
        cam = self._cam()
        # 800px / 10 units = 80 px/unit
        self.assertAlmostEqual(cam.pixel_ratio, 80.0)

    def test_initial_width_height(self) -> None:
        cam = self._cam()
        self.assertAlmostEqual(cam.width, 10.0)
        self.assertAlmostEqual(cam.height, 7.5)  # 600 / 80 = 7.5

    def test_invalid_target_width_raises(self) -> None:
        with self.assertRaises(ValueError):
            Camera2D(viewport=(800, 600), target_width=0.0)

    def test_invalid_viewport_raises(self) -> None:
        with self.assertRaises(ValueError):
            Camera2D(viewport=(0, 600), target_width=10.0)

    def test_set_both_dims_raises(self) -> None:
        cam = self._cam()
        # Internal method guard
        with self.assertRaises(ValueError):
            cam._set_dimensions(target_width=5.0, target_height=3.0)


class TestCamera2DDimensions(unittest.TestCase):
    """Setting width/height keeps aspect ratio correct."""

    @staticmethod
    def _cam() -> Camera2D:
        return Camera2D(viewport=(800, 600), target_width=10.0)

    def _check_dims(self, cam: Camera2D, w: float, h: float) -> None:
        self.assertTrue(isclose(cam.width, w, rel_tol=0.01), f"{cam.width} ≠ {w}")
        self.assertTrue(isclose(cam.height, h, rel_tol=0.01), f"{cam.height} ≠ {h}")

    def test_set_width(self) -> None:
        cam = self._cam()
        cam.width = 25.0
        self._check_dims(cam, 25.0, 18.75)

    def test_set_height(self) -> None:
        cam = self._cam()
        cam.height = 7.5
        self._check_dims(cam, 10.0, 7.5)

    def test_width_height_coupled(self) -> None:
        cam = self._cam()
        cam.width = 34.0
        self._check_dims(cam, 34.0, 25.5)

    def test_set_height_changes_width(self) -> None:
        cam = self._cam()
        cam.height = 18.75
        self._check_dims(cam, 25.0, 18.75)


class TestCamera2DEdges(unittest.TestCase):
    def _cam_at(self, x: float, y: float) -> Camera2D:
        cam = Camera2D(position=(x, y), target_width=10.0, viewport=(800, 600))
        return cam

    def test_edges_at_origin(self) -> None:
        cam = self._cam_at(0.0, 0.0)
        self.assertAlmostEqual(cam.left, -5.0)
        self.assertAlmostEqual(cam.right, 5.0)
        self.assertAlmostEqual(cam.top, 3.75)
        self.assertAlmostEqual(cam.bottom, -3.75)

    def test_edges_shifted(self) -> None:
        cam = self._cam_at(0.0, 1.0)
        self.assertAlmostEqual(cam.top, 4.75, places=4)
        self.assertAlmostEqual(cam.bottom, -2.75, places=4)

    def test_edges_far_position(self) -> None:
        cam = self._cam_at(15.0, -33.0)
        self.assertAlmostEqual(cam.right, 20.0, places=4)
        self.assertAlmostEqual(cam.left, 10.0, places=4)

    def test_corners_at_origin(self) -> None:
        cam = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
        self.assertEqual(cam.top_left, (-5.0, 3.75))
        self.assertEqual(cam.top_right, (5.0, 3.75))
        self.assertEqual(cam.bottom_left, (-5.0, -3.75))
        self.assertEqual(cam.bottom_right, (5.0, -3.75))


class TestCamera2DVisibility(unittest.TestCase):
    def _cam(self) -> Camera2D:
        return Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))

    def test_interior_point_visible(self) -> None:
        cam = self._cam()
        self.assertTrue(cam.point_is_visible((-4.0, 3.0)))

    def test_outside_x_not_visible(self) -> None:
        cam = self._cam()
        self.assertFalse(cam.point_is_visible((-7.0, 1.0)))

    def test_outside_y_not_visible(self) -> None:
        cam = self._cam()
        self.assertFalse(cam.point_is_visible((0.0, 5.0)))

    def test_boundary_right_visible(self) -> None:
        cam = self._cam()
        self.assertTrue(cam.point_is_visible((5.0, 3.75)))

    def test_just_past_boundary_not_visible(self) -> None:
        cam = self._cam()
        self.assertFalse(cam.point_is_visible((5.0, 4.0)))

    def test_visible_after_move(self) -> None:
        cam = Camera2D(position=(50.0, 24.0), target_width=10.0, viewport=(800, 600))
        self.assertTrue(cam.point_is_visible((46.0, 26.0)))
        self.assertFalse(cam.point_is_visible((0.0, 0.0)))


class TestCamera2DTranslation(unittest.TestCase):
    def _cam(self) -> Camera2D:
        return Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))

    def test_translate_to_screen(self) -> None:
        cam = self._cam()
        # (-1, -1) game → (320, 380) screen
        px, py = cam.translate_to_screen((-1.0, -1.0))
        self.assertAlmostEqual(px, 320.0, places=3)
        self.assertAlmostEqual(py, 380.0, places=3)

    def test_translate_to_screen_top_right(self) -> None:
        cam = self._cam()
        px, py = cam.translate_to_screen((4.0, -3.0))
        self.assertAlmostEqual(px, 720.0, places=3)
        self.assertAlmostEqual(py, 540.0, places=3)

    def test_translate_to_game(self) -> None:
        cam = self._cam()
        x, y = cam.translate_to_game((320.0, 380.0))
        self.assertAlmostEqual(x, -1.0, places=3)
        self.assertAlmostEqual(y, -1.0, places=3)

    def test_translate_to_game_centre(self) -> None:
        cam = self._cam()
        x, y = cam.translate_to_game((400.0, 300.0))
        self.assertAlmostEqual(x, 0.0, places=3)
        self.assertAlmostEqual(y, 0.0, places=3)

    def test_round_trip_game_screen_game(self) -> None:
        cam = self._cam()
        for gx, gy in [(-1.0, -1.0), (4.0, -3.0), (-6.0, 4.0), (0.0, 0.0)]:
            sx, sy = cam.translate_to_screen((gx, gy))
            rx, ry = cam.translate_to_game((sx, sy))
            self.assertAlmostEqual(rx, gx, places=4, msg=f"round-trip x failed for {(gx, gy)}")
            self.assertAlmostEqual(ry, gy, places=4, msg=f"round-trip y failed for {(gx, gy)}")

    def test_round_trip_screen_game_screen(self) -> None:
        cam = self._cam()
        for sx, sy in [(320.0, 380.0), (720.0, 540.0), (-80.0, -20.0)]:
            gx, gy = cam.translate_to_game((sx, sy))
            rx, ry = cam.translate_to_screen((gx, gy))
            self.assertAlmostEqual(rx, sx, places=4, msg=f"round-trip sx failed for {(sx, sy)}")
            self.assertAlmostEqual(ry, sy, places=4, msg=f"round-trip sy failed for {(sx, sy)}")

    def test_translate_to_screen_invalid_type_raises(self) -> None:
        cam = self._cam()
        with self.assertRaises(TypeError):
            cam.translate_to_screen("not_a_point")  # type: ignore[arg-type]

    def test_translate_to_screen_dict_raises(self) -> None:
        cam = self._cam()
        with self.assertRaises(TypeError):
            cam.translate_to_screen({"x": 1.0, "y": 1.0})  # type: ignore[arg-type]


class TestCamera2DWithDotXY(unittest.TestCase):
    """Camera2D accepts objects with .x and .y attributes."""

    class Vec:
        def __init__(self, x: float, y: float) -> None:
            self.x = x
            self.y = y

    def test_translate_to_screen_with_object(self) -> None:
        cam = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
        pt = self.Vec(-1.0, -1.0)
        px, py = cam.translate_to_screen(pt)  # type: ignore[arg-type]
        self.assertAlmostEqual(px, 320.0, places=3)
        self.assertAlmostEqual(py, 380.0, places=3)

    def test_point_is_visible_with_object(self) -> None:
        cam = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
        self.assertTrue(cam.point_is_visible(self.Vec(0.0, 0.0)))  # type: ignore[arg-type]


class TestCamera2DPositionMove(unittest.TestCase):
    def test_position_getter_setter(self) -> None:
        cam = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
        cam.position = (500.0, 500.0)
        self.assertAlmostEqual(cam.position[0], 500.0)
        self.assertAlmostEqual(cam.position[1], 500.0)

    def test_edges_update_after_position_change(self) -> None:
        cam = Camera2D(position=(0.0, 0.0), target_width=10.0, viewport=(800, 600))
        cam.position = (10.0, 0.0)
        self.assertAlmostEqual(cam.left, 5.0, places=4)
        self.assertAlmostEqual(cam.right, 15.0, places=4)


if __name__ == "__main__":
    unittest.main()
