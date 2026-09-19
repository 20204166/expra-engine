"""Tests for runtime event dataclasses.

Semantics adapted from PPB test_events.py (PursuedPyBear, Artistic
License 2.0). Adapted to Expra's event shapes (no PPB-specific fields).
"""

import unittest
from dataclasses import fields

from expra_engine.runtime.events import (
    Idle,
    Quit,
    ReplaceScene,
    SceneContinued,
    ScenePaused,
    SceneStarted,
    SceneStopped,
    StartScene,
    StopScene,
    Update,
)


class TestUpdateEvent(unittest.TestCase):
    def test_has_time_delta(self) -> None:
        e = Update(0.016)
        self.assertAlmostEqual(e.time_delta, 0.016)

    def test_is_dataclass(self) -> None:
        flds = {f.name for f in fields(Update)}
        self.assertIn("time_delta", flds)


class TestIdleEvent(unittest.TestCase):
    def test_has_time_delta(self) -> None:
        e = Idle(0.033)
        self.assertAlmostEqual(e.time_delta, 0.033)


class TestQuitEvent(unittest.TestCase):
    def test_instantiates(self) -> None:
        e = Quit()
        self.assertIsInstance(e, Quit)


class TestSceneLifecycleEvents(unittest.TestCase):
    def test_scene_started(self) -> None:
        e = SceneStarted()
        self.assertIsInstance(e, SceneStarted)

    def test_scene_stopped(self) -> None:
        e = SceneStopped()
        self.assertIsInstance(e, SceneStopped)

    def test_scene_paused(self) -> None:
        e = ScenePaused()
        self.assertIsInstance(e, ScenePaused)

    def test_scene_continued(self) -> None:
        e = SceneContinued()
        self.assertIsInstance(e, SceneContinued)


class TestStartScene(unittest.TestCase):
    def test_new_scene_stored(self) -> None:
        sentinel = object()
        e = StartScene(sentinel)
        self.assertIs(e.new_scene, sentinel)

    def test_default_kwargs_empty(self) -> None:
        e = StartScene(object())
        self.assertEqual(e.kwargs, {})

    def test_custom_kwargs(self) -> None:
        e = StartScene(object(), kwargs={"level": 2})
        self.assertEqual(e.kwargs["level"], 2)


class TestReplaceScene(unittest.TestCase):
    def test_new_scene_stored(self) -> None:
        sentinel = object()
        e = ReplaceScene(sentinel)
        self.assertIs(e.new_scene, sentinel)


class TestStopScene(unittest.TestCase):
    def test_instantiates(self) -> None:
        e = StopScene()
        self.assertIsInstance(e, StopScene)


if __name__ == "__main__":
    unittest.main()
