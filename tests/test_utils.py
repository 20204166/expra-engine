"""Tests for core/utils.py — camel_to_snake and get_time."""

import unittest
from time import perf_counter

from expra_engine.core.string_utils import camel_to_snake as string_camel_to_snake
from expra_engine.core.utils import camel_to_snake, get_time


class TestCamelToSnake(unittest.TestCase):
    def test_reuses_string_conversion_owner(self) -> None:
        self.assertIs(camel_to_snake, string_camel_to_snake)

    def test_simple_word(self) -> None:
        self.assertEqual(camel_to_snake("Update"), "update")

    def test_two_words(self) -> None:
        self.assertEqual(camel_to_snake("SceneStarted"), "scene_started")

    def test_all_caps_abbreviation(self) -> None:
        # "SceneID" → regex splits at the ID boundary → "scene_id"
        self.assertEqual(camel_to_snake("SceneID"), "scene_id")

    def test_idle(self) -> None:
        self.assertEqual(camel_to_snake("Idle"), "idle")

    def test_quit(self) -> None:
        self.assertEqual(camel_to_snake("Quit"), "quit")

    def test_already_snake(self) -> None:
        self.assertEqual(camel_to_snake("already_snake"), "already_snake")

    def test_three_words(self) -> None:
        self.assertEqual(camel_to_snake("SceneStopped"), "scene_stopped")

    def test_scene_paused(self) -> None:
        self.assertEqual(camel_to_snake("ScenePaused"), "scene_paused")

    def test_caching_returns_same_result(self) -> None:
        r1 = camel_to_snake("Update")
        r2 = camel_to_snake("Update")
        self.assertIs(r1, r2)

    def test_handler_name_prefix(self) -> None:
        # Verify the on_ prefix convention used by event_queue
        handler = "on_" + camel_to_snake("SceneStarted")
        self.assertEqual(handler, "on_scene_started")


class TestGetTime(unittest.TestCase):
    def test_returns_float(self) -> None:
        t = get_time()
        self.assertIsInstance(t, float)

    def test_monotonically_non_decreasing(self) -> None:
        t1 = get_time()
        t2 = get_time()
        self.assertGreaterEqual(t2, t1)

    def test_consistent_with_perf_counter(self) -> None:
        before = perf_counter()
        t = get_time()
        after = perf_counter()
        self.assertGreaterEqual(t, before)
        self.assertLessEqual(t, after)


if __name__ == "__main__":
    unittest.main()
