"""Tests for the deterministic, renderer-neutral runtime timeline."""

import unittest
from math import inf, nan

from expra_engine.runtime.events import Update
from expra_engine.runtime.system import RuntimeSystem
from expra_engine.runtime.timeline import Timeline


class TestTimelineUpdateContract(unittest.TestCase):
    def test_schedule_rejects_non_finite_timing_values(self) -> None:
        timeline = Timeline()

        for value in (nan, inf, -inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    timeline.schedule(delay=value)
                with self.assertRaises(ValueError):
                    timeline.schedule(duration=value)

    def test_advance_rejects_non_finite_timing_values(self) -> None:
        timeline = Timeline()

        for value in (nan, inf, -inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    timeline.advance(value)
                with self.assertRaises(ValueError):
                    timeline.advance(0.0, unscaled_delta=value)

    def test_is_a_runtime_system_and_consumes_update_events(self) -> None:
        timeline = Timeline()
        self.assertIsInstance(timeline, RuntimeSystem)
        values: list[float] = []
        timeline.schedule(duration=1.0, on_update=values.append)

        timeline.on_update(Update(0.25), None)

        self.assertEqual(values, [0.25])

    def test_delay_holds_progress_until_delay_has_elapsed(self) -> None:
        values: list[float] = []
        timeline = Timeline()
        timeline.schedule(delay=0.5, duration=1.0, on_update=values.append)

        timeline.advance(0.25)
        self.assertEqual(values, [])
        timeline.advance(0.25)
        self.assertEqual(values, [0.0])

    def test_interpolation_reaches_one_and_completes(self) -> None:
        events: list[object] = []
        timeline = Timeline()
        timeline.schedule(
            duration=1.0,
            on_update=lambda progress: events.append(progress),
            on_complete=lambda: events.append("complete"),
        )

        timeline.advance(0.25)
        timeline.advance(0.75)

        self.assertEqual(events, [0.25, 1.0, "complete"])

    def test_callback_order_is_update_then_complete(self) -> None:
        events: list[str] = []
        timeline = Timeline()
        timeline.schedule(
            duration=1.0,
            on_update=lambda _progress: events.append("update"),
            on_complete=lambda: events.append("complete"),
        )

        timeline.advance(1.0)

        self.assertEqual(events, ["update", "complete"])

    def test_update_callback_can_cancel_before_completion(self) -> None:
        events: list[str] = []
        timeline = Timeline()
        handle = None

        def on_update(_progress: float) -> None:
            events.append("update")
            assert handle is not None
            handle.cancel()

        handle = timeline.schedule(
            duration=1.0,
            on_update=on_update,
            on_complete=lambda: events.append("complete"),
        )

        timeline.advance(1.0)

        self.assertEqual(events, ["update"])

    def test_pause_and_resume_freeze_progress(self) -> None:
        values: list[float] = []
        timeline = Timeline()
        timeline.schedule(duration=1.0, on_update=values.append)

        timeline.advance(0.25)
        timeline.pause()
        timeline.advance(0.5)
        timeline.resume()
        timeline.advance(0.25)

        self.assertEqual(values, [0.25, 0.5])

    def test_cancel_prevents_future_callbacks(self) -> None:
        values: list[float] = []
        timeline = Timeline()
        handle = timeline.schedule(duration=1.0, on_update=values.append)

        self.assertTrue(handle.cancel())
        timeline.advance(1.0)

        self.assertEqual(values, [])
        self.assertFalse(handle.cancel())

    def test_loop_catches_up_without_dropping_large_delta(self) -> None:
        completions: list[int] = []
        timeline = Timeline()
        timeline.schedule(
            duration=0.25,
            loop=True,
            on_complete=lambda: completions.append(1),
        )

        timeline.advance(1.1)

        self.assertEqual(len(completions), 4)
        self.assertAlmostEqual(timeline.progress, 0.4)

    def test_zero_duration_is_bounded_for_looping_timeline(self) -> None:
        completions: list[int] = []
        timeline = Timeline()
        timeline.schedule(
            duration=0.0,
            loop=True,
            on_complete=lambda: completions.append(1),
        )

        timeline.advance(10.0)

        self.assertEqual(len(completions), 1)
        self.assertTrue(timeline.active)

    def test_scaled_and_unscaled_time_are_distinct_injected_deltas(self) -> None:
        scaled: list[float] = []
        unscaled: list[float] = []
        timeline = Timeline()
        timeline.schedule(duration=1.0, on_update=scaled.append, clock="scaled")
        timeline.schedule(duration=1.0, on_update=unscaled.append, clock="unscaled")

        timeline.advance(0.25, unscaled_delta=0.5)

        self.assertEqual(scaled, [0.25])
        self.assertEqual(unscaled, [0.5])

    def test_unscaled_delta_provider_is_used_by_update_events(self) -> None:
        values: list[float] = []
        timeline = Timeline(unscaled_delta=lambda _event: 0.5)
        timeline.schedule(duration=1.0, on_update=values.append, clock="unscaled")

        timeline.on_update(Update(0.25), None)

        self.assertEqual(values, [0.5])

    def test_stop_cancels_all_pending_work(self) -> None:
        values: list[float] = []
        timeline = Timeline()
        timeline.schedule(duration=1.0, on_update=values.append)

        timeline.stop()
        timeline.advance(1.0)

        self.assertFalse(timeline.active)
        self.assertEqual(values, [])


if __name__ == "__main__":
    unittest.main()
