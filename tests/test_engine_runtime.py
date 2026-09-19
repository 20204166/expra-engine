"""Tests for Engine runtime integration — tick, scene stack, systems.

Tests cover:
  - tick() returns dt and drives events
  - tick() in non-PLAY state returns 0 (safe)
  - SceneStarted fires on play()
  - SceneStopped fires on stop()
  - Update fires via tick() → RuntimeClock
  - Push/pop scene stack with lifecycle events
  - replace_scene signals SceneStopped + SceneStarted
  - Edit scene unchanged after runtime scene transitions
  - RuntimeSystem.start() / .stop() called on play/stop
  - loop_once() is an alias for tick()
"""

import unittest
from typing import Any

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.runtime.events import (
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
from expra_engine.runtime.system import RuntimeSystem


class _EventLog(RuntimeSystem):
    """RuntimeSystem that logs all events it handles."""

    def __init__(self) -> None:
        self.started_count = 0
        self.stopped_count = 0
        self.events: list[Any] = []
        self._engine: Any = None

    def start(self, engine: Engine) -> None:
        self.started_count += 1
        self._engine = engine

    def stop(self) -> None:
        self.stopped_count += 1

    def on_scene_started(self, event: SceneStarted, signal: Any) -> None:
        self.events.append(event)

    def on_scene_stopped(self, event: SceneStopped, signal: Any) -> None:
        self.events.append(event)

    def on_scene_paused(self, event: ScenePaused, signal: Any) -> None:
        self.events.append(event)

    def on_scene_continued(self, event: SceneContinued, signal: Any) -> None:
        self.events.append(event)

    def on_update(self, event: Update, signal: Any) -> None:
        self.events.append(event)


def _engine_with_log() -> tuple[Engine, _EventLog]:
    engine = Engine()
    log = _EventLog()
    engine.add_system(log)
    scene = Scene("TestScene")
    engine.set_scene(scene)
    return engine, log


class TestEngineTick(unittest.TestCase):
    def test_tick_in_edit_state_returns_zero(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        dt = engine.tick(0.016)
        self.assertAlmostEqual(dt, 0.0)

    def test_tick_in_paused_state_returns_zero(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        engine.pause()
        dt = engine.tick(0.016)
        self.assertAlmostEqual(dt, 0.0)

    def test_tick_in_play_returns_dt(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        dt = engine.tick(0.016)
        self.assertAlmostEqual(dt, 0.016)

    def test_loop_once_alias(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        dt = engine.loop_once(0.016)
        self.assertAlmostEqual(dt, 0.016)

    def test_tick_drives_update_via_clock(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        # One full fixed step (1/60 ≈ 0.0167) should fire exactly 1 Update
        engine.tick(1.0 / 60.0)
        updates = [e for e in log.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 1)

    def test_tick_large_dt_fires_multiple_updates(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        engine.tick(3.0 / 60.0)
        updates = [e for e in log.events if isinstance(e, Update)]
        self.assertEqual(len(updates), 3)


class TestEngineSystemLifecycle(unittest.TestCase):
    def test_system_start_called_on_play(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        self.assertEqual(log.started_count, 1)

    def test_system_stop_called_on_stop(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        engine.stop()
        self.assertEqual(log.stopped_count, 1)

    def test_system_receives_engine_on_start(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        self.assertIs(log._engine, engine)

    def test_add_remove_system(self) -> None:
        engine = Engine()
        system = _EventLog()
        engine.add_system(system)
        engine.remove_system(system)
        engine.set_scene(Scene("T"))
        engine.play()
        self.assertEqual(system.started_count, 0)

    def test_remove_nonexistent_system_safe(self) -> None:
        engine = Engine()
        engine.remove_system(_EventLog())  # must not raise


class TestEngineSceneLifecycleEvents(unittest.TestCase):
    def test_scene_started_fires_on_play(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        started = [e for e in log.events if isinstance(e, SceneStarted)]
        self.assertEqual(len(started), 1)

    def test_scene_stopped_fires_on_stop(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        log.events.clear()
        engine.stop()
        stopped = [e for e in log.events if isinstance(e, SceneStopped)]
        self.assertEqual(len(stopped), 1)


class TestEngineSceneStack(unittest.TestCase):
    def test_push_scene_activates_new_scene(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        new_scene = Scene("Overlay")
        engine.push_scene(new_scene)
        self.assertIs(engine.active_scene, new_scene)

    def test_pop_scene_restores_previous(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        base = engine.active_scene
        new_scene = Scene("Overlay")
        engine.push_scene(new_scene)
        engine.pop_scene()
        self.assertIs(engine.active_scene, base)

    def test_push_fires_paused_then_started(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        log.events.clear()
        engine.push_scene(Scene("Overlay"))
        types = [type(e) for e in log.events]
        self.assertIn(ScenePaused, types)
        self.assertIn(SceneStarted, types)
        # Paused must come before Started
        self.assertLess(types.index(ScenePaused), types.index(SceneStarted))

    def test_pop_fires_stopped_then_continued(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        engine.push_scene(Scene("Overlay"))
        log.events.clear()
        engine.pop_scene()
        types = [type(e) for e in log.events]
        self.assertIn(SceneStopped, types)
        self.assertIn(SceneContinued, types)
        self.assertLess(types.index(SceneStopped), types.index(SceneContinued))

    def test_replace_scene_fires_stopped_then_started(self) -> None:
        engine, log = _engine_with_log()
        engine.play()
        log.events.clear()
        engine.replace_scene(Scene("NewScene"))
        types = [type(e) for e in log.events]
        self.assertIn(SceneStopped, types)
        self.assertIn(SceneStarted, types)
        self.assertLess(types.index(SceneStopped), types.index(SceneStarted))

    def test_push_requires_play_state(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        with self.assertRaises(RuntimeError):
            engine.push_scene(Scene("Overlay"))

    def test_pop_requires_play_state(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        with self.assertRaises(RuntimeError):
            engine.pop_scene()

    def test_start_scene_request_pushes_materialized_scene(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        requested = Scene("Requested")
        engine._eq.signal(StartScene(lambda **kwargs: requested, kwargs={"level": 2}))  # type: ignore[union-attr]
        engine.tick(0.0)
        self.assertIs(engine.active_scene, requested)

    def test_stop_scene_request_pops_scene(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        base = engine.active_scene
        engine.push_scene(Scene("Overlay"))
        engine._eq.signal(StopScene())  # type: ignore[union-attr]
        engine.tick(0.0)
        self.assertIs(engine.active_scene, base)

    def test_replace_scene_request_replaces_scene(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        requested = Scene("Replacement")
        engine._eq.signal(ReplaceScene(requested))  # type: ignore[union-attr]
        engine.tick(0.0)
        self.assertIs(engine.active_scene, requested)

    def test_quit_request_stops_runtime(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Base"))
        engine.play()
        engine._eq.signal(Quit())  # type: ignore[union-attr]
        engine.tick(0.0)
        self.assertEqual(engine.run_state, EngineRunState.EDIT)


class TestEngineEditSceneIsolation(unittest.TestCase):
    """Runtime scene transitions must never corrupt the editor's edit scene."""

    def test_edit_scene_unchanged_after_push_pop(self) -> None:
        engine = Engine()
        original = Scene("Edit", scene_id="edit-1")
        engine.set_scene(original)
        engine.play()
        engine.push_scene(Scene("Overlay"))
        engine.pop_scene()
        engine.stop()
        self.assertIs(engine.edit_scene, original)

    def test_edit_scene_unchanged_after_replace(self) -> None:
        engine = Engine()
        original = Scene("Edit", scene_id="edit-1")
        engine.set_scene(original)
        engine.play()
        engine.replace_scene(Scene("NewScene"))
        engine.stop()
        self.assertIs(engine.edit_scene, original)


if __name__ == "__main__":
    unittest.main()
