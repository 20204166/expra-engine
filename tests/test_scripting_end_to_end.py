"""End-to-end project script path regression."""

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.scene import Scene
from expra_engine.editor.script_tools import create_behaviour_script
from expra_engine.export.manifest import AssetManifest
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry

SCRIPT = """\
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed

class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)
    health = exposed(100, min=0, max=100)

    def on_update(self, dt):
        if self.input.is_held('move_right'):
            self.require_component(TransformComponent).x += self.speed * dt
"""


class ScriptingEndToEndTests(unittest.TestCase):
    def test_project_script_runs_and_is_exported_as_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "player.py"
            script.write_text(SCRIPT, encoding="utf-8")
            resource = ResourceId.parse("project://scripts/player.py")
            scene = Scene("Level", scene_id="level")
            entity = scene.create_entity("Player", entity_id="player")
            entity.add_component(TransformComponent())
            entity.add_component(
                ScriptComponent(resource, "PlayerBehaviour", exposed_values={"speed": 200.0})
            )
            serialized = json.loads(json.dumps(scene.to_dict()))
            engine = Engine()
            engine.set_scene(Scene.from_dict(serialized))
            engine.set_script_registry(ScriptRegistry(root))
            engine.input_map.bind(ActionId("move_right"), PhysicalInput("keyboard", "d"))
            engine.play()
            engine.input_map.press(PhysicalInput("keyboard", "d"))
            engine.tick(0.5)
            runtime = engine.active_scene
            assert runtime is not None
            transform = runtime.entities[0].get_component(TransformComponent)
            assert transform is not None
            self.assertAlmostEqual(transform.x, 100.0)
            engine.stop()
            self.assertAlmostEqual(scene.entities[0].get_component(TransformComponent).x, 0.0)  # type: ignore[union-attr]
            manifest = AssetManifest.collect(root, include_source=True)
            self.assertIn("scripts/player.py", {entry.path for entry in manifest.entries})

    def test_template_uses_public_behaviour_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resource = create_behaviour_script(
                Path(directory), "scripts/player.py", "PlayerBehaviour"
            )
            self.assertEqual(str(resource), "project://scripts/player.py")
            text = (Path(directory) / "scripts/player.py").read_text(encoding="utf-8")
            self.assertIn("Behaviour, exposed", text)
            self.assertNotIn("eval(", text)
            self.assertNotIn("exec(", text)


if __name__ == "__main__":
    unittest.main()
