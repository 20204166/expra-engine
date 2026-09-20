"""Tests for project script loading and canonical runtime ownership."""

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.scene import Scene
from expra_engine.runtime.behaviour import Behaviour
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptLoadError, ScriptRegistry
from expra_engine.runtime.system import RuntimeSystem

SCRIPT = """\
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour

class PlayerBehaviour(Behaviour):
    def on_update(self, dt):
        self.require_component(TransformComponent).x += dt
"""


class BehaviourSystemTests(unittest.TestCase):
    def test_no_script_and_unrelated_script_keep_default_system_behavior(self) -> None:
        script = "from expra_engine.runtime.behaviour import Behaviour\nclass PlayerBehaviour(Behaviour):\n    pass\n"

        class DefaultMovement(RuntimeSystem):
            def on_frame_update(self, event, signal):
                scene = self.engine.active_scene
                assert scene is not None
                transform = scene.entities[0].get_component(TransformComponent)
                assert transform is not None
                transform.x += event.time_delta

            def start(self, engine):
                self.engine = engine

        def run(with_script: bool) -> float:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / "scripts" / "player.py").write_text(script, encoding="utf-8")
                scene = Scene("Level")
                entity = scene.create_entity("Player")
                entity.add_component(TransformComponent())
                if with_script:
                    entity.add_component(
                        ScriptComponent("project://scripts/player.py", "PlayerBehaviour")
                    )
                engine = Engine()
                engine.set_scene(scene)
                engine.add_system(DefaultMovement())
                if with_script:
                    engine.set_script_registry(ScriptRegistry(root))
                engine.play()
                engine.tick(0.25)
                active_scene = engine.active_scene
                assert active_scene is not None
                transform = active_scene.entities[0].get_component(TransformComponent)
                assert transform is not None
                return transform.x

        self.assertEqual(run(False), run(True))

    def test_registry_loads_project_script_without_arbitrary_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "player.py").write_text(SCRIPT, encoding="utf-8")
            registry = ScriptRegistry(root)
            cls = registry.resolve("project://scripts/player.py", "PlayerBehaviour")
            self.assertTrue(issubclass(cls, Behaviour))
            with self.assertRaises(ScriptLoadError):
                registry.resolve("project://../outside.py", "PlayerBehaviour")
            with self.assertRaises(ScriptLoadError):
                registry.resolve("project://__import__('os').py", "PlayerBehaviour")
            with self.assertRaises(ScriptLoadError):
                registry.resolve("/tmp/player.py", "PlayerBehaviour")

    def test_registry_supports_trusted_relative_project_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "helper.py").write_text("VALUE = 7\n", encoding="utf-8")
            (root / "scripts" / "player.py").write_text(
                "from .helper import VALUE\n"
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    value = VALUE\n",
                encoding="utf-8",
            )
            cls = ScriptRegistry(root).resolve("project://scripts/player.py", "PlayerBehaviour")
            self.assertEqual(cast(Any, cls()).value, 7)

    def test_system_instantiates_script_component_and_dispatches_frame_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "player.py").write_text(SCRIPT, encoding="utf-8")
            registry = ScriptRegistry(root)
            scene = Scene("Level")
            entity = scene.create_entity("Player")
            entity.add_component(TransformComponent())
            entity.add_component(ScriptComponent("project://scripts/player.py", "PlayerBehaviour"))
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(registry)
            engine.play()
            engine.tick(0.25)
            runtime = engine.active_scene
            assert runtime is not None
            transform = runtime.entities[0].get_component(TransformComponent)
            assert transform is not None
            self.assertAlmostEqual(transform.x, 0.25)
            self.assertEqual(len(engine.behaviour_system.instances), 1)
            engine.stop()
            self.assertEqual(engine.behaviour_system.instances, ())

    def test_reload_failure_preserves_known_good_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(SCRIPT, encoding="utf-8")
            registry = ScriptRegistry(root)
            scene = Scene("Level")
            entity = scene.create_entity("Player")
            entity.add_component(TransformComponent())
            component = ScriptComponent("project://scripts/player.py", "PlayerBehaviour")
            entity.add_component(component)
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(registry)
            engine.play()
            instance = engine.behaviour_system.instances[0]
            script.write_text("syntax error =", encoding="utf-8")
            with self.assertRaises(ScriptLoadError):
                engine.behaviour_system.reload_script(component.script_id)
            self.assertIs(engine.behaviour_system.instances[0], instance)
            engine.stop()

    def test_start_failure_rolls_back_runtime_and_edit_state(self) -> None:
        script = SCRIPT.replace("class PlayerBehaviour", "class BrokenBehaviour").replace(
            "def on_update(self, dt):",
            "def on_start(self):\n        raise RuntimeError('boom')\n\n    def on_update(self, dt):",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "broken.py").write_text(script, encoding="utf-8")
            scene = Scene("Level")
            entity = scene.create_entity("Broken")
            entity.add_component(ScriptComponent("project://scripts/broken.py", "BrokenBehaviour"))
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(ScriptRegistry(root))
            with self.assertRaises(RuntimeError):
                engine.play()
            self.assertEqual(engine.run_state.value, "edit")
            self.assertIs(engine.edit_scene, scene)

    def test_missing_optional_script_keeps_default_system_available(self) -> None:
        class DefaultMovement(RuntimeSystem):
            def start(self, engine):
                self.engine = engine

            def on_frame_update(self, event, signal):
                scene = self.engine.active_scene
                assert scene is not None
                transform = scene.entities[0].get_component(TransformComponent)
                assert transform is not None
                transform.x += event.time_delta

        scene = Scene("Level")
        entity = scene.create_entity("Player")
        entity.add_component(TransformComponent())
        entity.add_component(ScriptComponent("project://scripts/missing.py", "Missing"))
        engine = Engine()
        engine.set_scene(scene)
        engine.add_system(DefaultMovement())
        engine.set_script_registry(ScriptRegistry(Path.cwd()))
        engine.play()
        engine.tick(0.25)
        active_scene = engine.active_scene
        assert active_scene is not None
        transform = active_scene.entities[0].get_component(TransformComponent)
        assert transform is not None
        self.assertEqual(transform.x, 0.25)
        self.assertEqual(len(engine.behaviour_system.errors), 1)


if __name__ == "__main__":
    unittest.main()
