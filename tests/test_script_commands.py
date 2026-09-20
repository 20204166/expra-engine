import unittest

from expra_engine.core.scene import Scene
from expra_engine.editor.commands import SetExposedValueCommand
from expra_engine.runtime.script_component import ScriptComponent


class ScriptCommandTests(unittest.TestCase):
    def test_exposed_edit_undo_redo_targets_stable_entity(self) -> None:
        scene = Scene("Level")
        entity = scene.create_entity("Player")
        entity.add_component(
            ScriptComponent(
                "project://scripts/player.py", "PlayerBehaviour", exposed_values={"speed": 100.0}
            )
        )
        command = SetExposedValueCommand(scene, entity.entity_id, 0, "speed", 160.0)
        command.execute()
        component = entity.components[0]
        assert isinstance(component, ScriptComponent)
        self.assertEqual(component.exposed_values["speed"], 160.0)
        command.undo()
        self.assertEqual(component.exposed_values["speed"], 100.0)
        command.execute()
        scene.remove_entity(entity.entity_id)
        command.undo()
        self.assertIsNone(scene.find_entity(entity.entity_id))


if __name__ == "__main__":
    unittest.main()
