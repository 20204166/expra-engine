from __future__ import annotations

import unittest

from expra_engine.runtime.smooth_follow import SmoothFollow


class SmoothFollowTests(unittest.TestCase):
    def test_moves_toward_target_without_overshooting(self) -> None:
        follow = SmoothFollow(speed=5.0)
        x, y = follow.update(1.0, 10.0, 10.0)
        self.assertGreater(x, 0.0)
        self.assertLess(x, 10.0)
        self.assertGreater(y, 0.0)

    def test_large_dt_approaches_target(self) -> None:
        follow = SmoothFollow(speed=5.0)
        x, y = follow.update(100.0, 5.0, 3.0)
        self.assertAlmostEqual(x, 5.0, places=2)
        self.assertAlmostEqual(y, 3.0, places=2)

    def test_zero_dt_and_snap(self) -> None:
        follow = SmoothFollow(speed=5.0, x=1.0, y=2.0)
        self.assertEqual(follow.update(0.0, 10.0, 10.0), (1.0, 2.0))
        follow.snap_to(7.0, 3.0)
        self.assertEqual((follow.x, follow.y), (7.0, 3.0))

    def test_invalid_speed_and_dt_raise(self) -> None:
        with self.assertRaises(ValueError):
            SmoothFollow(speed=0.0)
        with self.assertRaises(ValueError):
            SmoothFollow().update(-1.0, 0.0, 0.0)


if __name__ == "__main__":
    unittest.main()
