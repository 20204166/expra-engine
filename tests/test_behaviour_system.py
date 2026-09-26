"""Tests for project script loading and canonical runtime ownership."""

import os
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

    def test_registries_isolate_same_relative_module_path_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_root = root / "first"
            second_root = root / "second"
            for project_root, value in ((first_root, 1), (second_root, 2)):
                (project_root / "scripts").mkdir(parents=True)
                (project_root / "scripts" / "player.py").write_text(
                    "from expra_engine.runtime.behaviour import Behaviour\n"
                    f"class PlayerBehaviour(Behaviour):\n    value = {value}\n",
                    encoding="utf-8",
                )

            first_registry = ScriptRegistry(first_root)
            second_registry = ScriptRegistry(second_root)
            first = first_registry.resolve("project://scripts/player.py", "PlayerBehaviour")
            second = second_registry.resolve("project://scripts/player.py", "PlayerBehaviour")

            self.assertEqual(cast(Any, first()).value, 1)
            self.assertEqual(cast(Any, second()).value, 2)
            self.assertNotEqual(first.__module__, second.__module__)

    def test_registry_failed_reload_restores_cached_module_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(SCRIPT, encoding="utf-8")
            registry = ScriptRegistry(root)
            original = registry.resolve("project://scripts/player.py", "PlayerBehaviour")
            script.write_text("syntax error =", encoding="utf-8")

            with self.assertRaises(ScriptLoadError):
                registry.reload("project://scripts/player.py")

            self.assertIs(
                registry.resolve("project://scripts/player.py", "PlayerBehaviour"), original
            )
            self.assertEqual(registry.generation("project://scripts/player.py"), 0)

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

    def test_registry_reload_reads_changed_source_with_same_size_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    version = 1\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry(root)
            first_class = registry.resolve("project://scripts/player.py", "PlayerBehaviour")
            self.assertEqual(cast(Any, first_class()).version, 1)
            original_stat = script.stat()
            script.write_text(
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    version = 2\n",
                encoding="utf-8",
            )
            os.utime(script, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

            registry.reload("project://scripts/player.py")

            reloaded = registry.resolve("project://scripts/player.py", "PlayerBehaviour")
            self.assertEqual(cast(Any, reloaded()).version, 2)

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

    def test_reload_start_failure_discards_all_staged_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(SCRIPT, encoding="utf-8")
            registry = ScriptRegistry(root)
            scene = Scene("Level")
            for entity_id in ("first", "second"):
                entity = scene.create_entity(entity_id, entity_id=entity_id)
                entity.add_component(
                    ScriptComponent("project://scripts/player.py", "PlayerBehaviour")
                )
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(registry)
            engine.play()
            system = engine.behaviour_system
            original_instances = system.instances
            script.write_text(
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "CREATED = []\n"
                "STARTS = 0\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    created = CREATED\n"
                "    def __init__(self):\n"
                "        global STARTS\n"
                "        super().__init__()\n"
                "        STARTS += 1\n"
                "        self.ordinal = STARTS\n"
                "        self.stopped = False\n"
                "        self.destroyed = False\n"
                "        self.created.append(self)\n"
                "    def on_start(self):\n"
                "        if self.ordinal == 2:\n"
                "            raise RuntimeError('replacement start failed')\n"
                "    def on_stop(self):\n"
                "        self.stopped = True\n"
                "    def on_destroy(self):\n"
                "        self.destroyed = True\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "replacement start failed"):
                system.reload_script("project://scripts/player.py")

            replacement_class = registry.resolve(
                "project://scripts/player.py", "PlayerBehaviour"
            )
            candidates = cast(Any, replacement_class).created
            self.assertEqual(len(candidates), 2)
            for candidate in candidates:
                self.assertIsNone(candidate.entity)
                self.assertFalse(candidate._started)
                self.assertTrue(candidate._destroyed)
                self.assertTrue(candidate.stopped)
            self.assertEqual(system.instances, original_instances)
            runtime_scene = engine.active_scene
            assert runtime_scene is not None
            for runtime_entity in runtime_scene.entities:
                self.assertEqual(len(runtime_entity.behaviours), 1)
            engine.stop()

    def test_reload_commits_replacement_even_if_retiring_old_instance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    def on_stop(self):\n"
                "        if getattr(self, 'fail_stop', False):\n"
                "            raise RuntimeError('old stop failed')\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry(root)
            scene = Scene("Level")
            entity = scene.create_entity("Player")
            component = ScriptComponent("project://scripts/player.py", "PlayerBehaviour")
            entity.add_component(component)
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(registry)
            engine.play()
            system = engine.behaviour_system
            old = system.instances[0]
            cast(Any, old).fail_stop = True
            script.write_text(
                "from expra_engine.runtime.behaviour import Behaviour\n"
                "class PlayerBehaviour(Behaviour):\n"
                "    version = 2\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "old stop failed"):
                system.reload_script(component.script_id)

            runtime_scene = engine.active_scene
            assert runtime_scene is not None
            runtime_entity = runtime_scene.find_entity(entity.entity_id)
            assert runtime_entity is not None
            self.assertEqual(len(runtime_entity.behaviours), 1)
            self.assertIsNot(runtime_entity.behaviours[0], old)
            self.assertEqual(system.instances, (runtime_entity.behaviours[0],))
            self.assertIsNone(old.entity)
            self.assertTrue(old._destroyed)
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

    def test_failed_scene_start_resets_and_detaches_the_failing_behaviour(self) -> None:
        script = """from expra_engine.runtime.behaviour import Behaviour
CREATED = []
class BrokenBehaviour(Behaviour):
    created = CREATED
    def __init__(self):
        super().__init__()
        self.destroyed = False
        self.created.append(self)
    def on_start(self):
        raise RuntimeError('start failed')
    def on_destroy(self):
        self.destroyed = True
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "broken.py").write_text(script, encoding="utf-8")
            registry = ScriptRegistry(root)
            scene = Scene("Level")
            entity = scene.create_entity("Broken")
            entity.add_component(
                ScriptComponent("project://scripts/broken.py", "BrokenBehaviour")
            )
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(registry)

            with self.assertRaisesRegex(RuntimeError, "start failed"):
                engine.play()

            behaviour_class = registry.resolve(
                "project://scripts/broken.py", "BrokenBehaviour"
            )
            behaviour = cast(Any, behaviour_class).created[0]
            self.assertIsNone(behaviour.entity)
            self.assertFalse(behaviour._started)
            self.assertTrue(behaviour._destroyed)
            self.assertEqual(engine.behaviour_system.instances, ())
            self.assertEqual(engine.behaviour_system._started_scenes, set())

    def test_stop_failure_still_detaches_other_instances_for_same_entity(self) -> None:
        script = """from expra_engine.runtime.behaviour import Behaviour
class FirstBehaviour(Behaviour):
    def on_stop(self):
        raise RuntimeError('first stop failed')
class SecondBehaviour(Behaviour):
    pass
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "player.py").write_text(script, encoding="utf-8")
            scene = Scene("Level")
            entity = scene.create_entity("Player")
            for class_name, order in (("FirstBehaviour", 0), ("SecondBehaviour", 1)):
                entity.add_component(
                    ScriptComponent(
                        "project://scripts/player.py", class_name, order=order
                    )
                )
            engine = Engine()
            engine.set_scene(scene)
            engine.set_script_registry(ScriptRegistry(root))
            engine.play()
            system = engine.behaviour_system
            runtime_entity = engine.active_scene.entities[0]  # type: ignore[union-attr]
            runtime_behaviours = runtime_entity.behaviours

            with self.assertRaisesRegex(RuntimeError, "first stop failed"):
                system.stop()

            self.assertEqual(runtime_entity.behaviours, ())
            self.assertTrue(all(behaviour.entity is None for behaviour in runtime_behaviours))
            self.assertTrue(all(behaviour._destroyed for behaviour in runtime_behaviours))
            self.assertEqual(system.instances, ())

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
