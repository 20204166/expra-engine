from __future__ import annotations

import unittest

from expra_engine.runtime.trail import TrailRenderer


class TrailRendererTests(unittest.TestCase):
    def test_records_first_point(self) -> None:
        trail = TrailRenderer()
        trail.update(0.0, 1.0, 2.0)
        self.assertEqual(len(trail.points), 1)

    def test_min_spacing_filters_close_points(self) -> None:
        trail = TrailRenderer(min_spacing=1.0)
        trail.update(0.0, 0.0, 0.0)
        trail.update(0.0, 0.5, 0.0)
        trail.update(0.0, 1.5, 0.0)
        self.assertEqual(len(trail.points), 2)

    def test_max_segments_and_lifetime_cull(self) -> None:
        trail = TrailRenderer(max_segments=3, min_spacing=0.0, max_lifetime=0.5)
        for index in range(5):
            trail.update(0.0, float(index), 0.0)
        self.assertEqual(len(trail.points), 3)
        trail.update(0.6, 5.0, 0.0)
        self.assertTrue(all(point.age < 0.5 for point in trail.points))

    def test_clear_and_invalid_configuration(self) -> None:
        trail = TrailRenderer(min_spacing=0.0)
        trail.update(0.0, 1.0, 0.0)
        trail.clear()
        self.assertEqual(trail.points, [])
        with self.assertRaises(ValueError):
            TrailRenderer(max_segments=0)
        with self.assertRaises(ValueError):
            TrailRenderer(min_spacing=-1.0)


if __name__ == "__main__":
    unittest.main()
