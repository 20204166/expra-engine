"""Tests for HitResult2D and TriggerEvent contracts."""

import unittest
from dataclasses import FrozenInstanceError

from expra_engine.runtime.physics import HitResult2D, TriggerEvent


class HitResult2DTests(unittest.TestCase):
    def test_no_hit_defaults(self) -> None:
        r = HitResult2D.no_hit()
        self.assertFalse(r.hit)
        self.assertIsNone(r.entity_id)
        self.assertIsNone(r.distance)

    def test_hit_requires_entity_id(self) -> None:
        with self.assertRaises(ValueError):
            HitResult2D(hit=True)

    def test_valid_hit(self) -> None:
        r = HitResult2D(hit=True, entity_id="e1", distance=5.0, fraction=0.5)
        self.assertTrue(r.hit)
        self.assertEqual(r.entity_id, "e1")
        self.assertEqual(r.distance, 5.0)

    def test_negative_distance_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HitResult2D(hit=True, entity_id="e1", distance=-1.0)

    def test_fraction_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HitResult2D(hit=True, entity_id="e1", fraction=1.5)
        with self.assertRaises(ValueError):
            HitResult2D(hit=True, entity_id="e1", fraction=-0.1)

    def test_nearest_returns_closest(self) -> None:
        results = [
            HitResult2D(hit=True, entity_id="far", distance=10.0),
            HitResult2D(hit=True, entity_id="near", distance=3.0),
            HitResult2D(hit=False),
        ]
        nearest = HitResult2D.nearest(results)
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest.entity_id, "near")  # type: ignore[union-attr]

    def test_nearest_all_no_hit_returns_none(self) -> None:
        self.assertIsNone(HitResult2D.nearest([HitResult2D.no_hit()]))

    def test_nearest_without_distance_placed_last(self) -> None:
        results = [
            HitResult2D(hit=True, entity_id="no_dist"),
            HitResult2D(hit=True, entity_id="has_dist", distance=1.0),
        ]
        nearest = HitResult2D.nearest(results)
        self.assertEqual(nearest.entity_id, "has_dist")  # type: ignore[union-attr]

    def test_immutable(self) -> None:
        r = HitResult2D.no_hit()
        with self.assertRaises(FrozenInstanceError):
            r.hit = True  # type: ignore[misc]


class TriggerEventTests(unittest.TestCase):
    def test_valid_phases(self) -> None:
        for phase in ("entered", "stayed", "exited"):
            evt = TriggerEvent(phase=phase, trigger_id="t1", body_id="b1")
            self.assertEqual(evt.phase, phase)

    def test_invalid_phase_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TriggerEvent(phase="hit", trigger_id="t1", body_id="b1")

    def test_empty_ids_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TriggerEvent(phase="entered", trigger_id="", body_id="b1")
        with self.assertRaises(ValueError):
            TriggerEvent(phase="entered", trigger_id="t1", body_id="")

    def test_immutable(self) -> None:
        evt = TriggerEvent("entered", "t1", "b1")
        with self.assertRaises(FrozenInstanceError):
            evt.phase = "exited"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
