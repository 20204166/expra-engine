"""Tests for Engine and EngineRunState."""

import unittest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene


class TestEngineRunState(unittest.TestCase):
    def test_initial_state_is_edit(self) -> None:
        engine = Engine()
        self.assertEqual(engine.run_state, EngineRunState.EDIT)

    def test_play_from_edit(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        changed = engine.play()
        self.assertTrue(changed)
        self.assertEqual(engine.run_state, EngineRunState.PLAY)

    def test_play_from_play_is_noop(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        changed = engine.play()
        self.assertFalse(changed)

    def test_pause_from_play(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        changed = engine.pause()
        self.assertTrue(changed)
        self.assertEqual(engine.run_state, EngineRunState.PAUSED)

    def test_pause_from_edit_is_noop(self) -> None:
        engine = Engine()
        changed = engine.pause()
        self.assertFalse(changed)

    def test_stop_from_play_restores_edit(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        changed = engine.stop()
        self.assertTrue(changed)
        self.assertEqual(engine.run_state, EngineRunState.EDIT)

    def test_stop_from_edit_is_noop(self) -> None:
        engine = Engine()
        changed = engine.stop()
        self.assertFalse(changed)

    def test_play_from_paused(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        engine.pause()
        changed = engine.play()
        self.assertTrue(changed)
        self.assertEqual(engine.run_state, EngineRunState.PLAY)


class TestEngineSceneIsolation(unittest.TestCase):
    """Play mode uses a runtime copy; Stop restores original edit scene."""

    def test_runtime_scene_is_copy(self) -> None:
        engine = Engine()
        scene = Scene("Level 1", scene_id="level-1")
        entity = scene.create_entity("Player", entity_id="p-1")
        entity.add_component(TransformComponent(x=0.0))
        engine.set_scene(scene)

        engine.play()
        runtime = engine.active_scene
        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertIsNot(runtime, scene)  # it's a copy

    def test_mutate_runtime_does_not_affect_edit_scene(self) -> None:
        engine = Engine()
        scene = Scene("Level 1")
        entity = scene.create_entity("Player", entity_id="p-1")
        entity.add_component(TransformComponent(x=0.0))
        engine.set_scene(scene)

        engine.play()
        runtime = engine.active_scene
        assert runtime is not None
        player = runtime.find_entity("p-1")
        assert player is not None
        transform = player.get_component(TransformComponent)
        assert transform is not None
        transform.x = 999.0  # mutate runtime

        engine.stop()
        edit_player = engine.edit_scene.find_entity("p-1")  # type: ignore[union-attr]
        assert edit_player is not None
        edit_transform = edit_player.get_component(TransformComponent)
        assert edit_transform is not None
        self.assertAlmostEqual(edit_transform.x, 0.0)  # edit scene unchanged

    def test_active_scene_returns_edit_in_edit_state(self) -> None:
        engine = Engine()
        scene = Scene("Test")
        engine.set_scene(scene)
        self.assertIs(engine.active_scene, scene)


class TestEngineUpdate(unittest.TestCase):
    def test_update_returns_zero_when_not_playing(self) -> None:
        engine = Engine()
        dt = engine.update()
        self.assertAlmostEqual(dt, 0.0)

    def test_update_returns_elapsed_when_playing(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        import time
        time.sleep(0.01)
        dt = engine.update()
        self.assertGreater(dt, 0.0)

    def test_update_with_explicit_dt(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("Test"))
        engine.play()
        dt = engine.update(0.016)
        self.assertAlmostEqual(dt, 0.016)


class TestEngineProject(unittest.TestCase):
    def test_set_project(self) -> None:
        from pathlib import Path

        from expra_engine.core.project import Project
        engine = Engine()
        project = Project("Test Project", Path("/tmp/test_project"))
        engine.set_project(project)
        self.assertIs(engine.project, project)


if __name__ == "__main__":
    unittest.main()
