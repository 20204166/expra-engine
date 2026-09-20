from __future__ import annotations

import unittest

from expra_engine.runtime.platformer import PlatformerController2d, PlatformerPhase


class PlatformerTests(unittest.TestCase):
    def test_starts_airborne_and_gravity_applies(self) -> None:
        controller = PlatformerController2d(gravity=10.0)
        self.assertEqual(controller.phase, PlatformerPhase.AIRBORNE)
        controller.update(1.0, 0.0)
        self.assertLess(controller.velocity[1], 0.0)

    def test_land_and_ground_jump(self) -> None:
        controller = PlatformerController2d(max_jumps=1)
        controller.land()
        self.assertTrue(controller.grounded)
        self.assertTrue(controller.jump())
        self.assertFalse(controller.grounded)

    def test_jumps_are_limited_and_landing_resets_them(self) -> None:
        controller = PlatformerController2d(max_jumps=2)
        controller.land()
        self.assertTrue(controller.jump())
        self.assertTrue(controller.jump())
        self.assertFalse(controller.jump())
        controller.land()
        self.assertEqual(controller.jumps_left, 2)

    def test_coyote_time_allows_short_late_jump(self) -> None:
        controller = PlatformerController2d(max_jumps=1, coyote_time=0.1)
        controller.land()
        controller.leave_ground()
        self.assertEqual(controller.phase, PlatformerPhase.COYOTE)
        self.assertTrue(controller.jump())

    def test_coyote_time_expires(self) -> None:
        controller = PlatformerController2d(max_jumps=1, coyote_time=0.1)
        controller.land()
        controller.leave_ground()
        controller.update(0.2, 0.0)
        self.assertEqual(controller.phase, PlatformerPhase.AIRBORNE)

    def test_horizontal_position_is_clamped(self) -> None:
        controller = PlatformerController2d(min_x=0.0, max_x=5.0)
        controller.land()
        controller.update(1.0, -10.0)
        self.assertEqual(controller.position[0], 0.0)

    def test_invalid_configuration_and_dt_raise(self) -> None:
        with self.assertRaises(ValueError):
            PlatformerController2d(max_jumps=0)
        with self.assertRaises(ValueError):
            PlatformerController2d(min_x=5.0, max_x=0.0)
        with self.assertRaises(ValueError):
            PlatformerController2d().update(-1.0, 0.0)


if __name__ == "__main__":
    unittest.main()
