import tempfile
import unittest
from pathlib import Path

from expra_engine.core.entity import Entity
from expra_engine.editor.script_tools import attach_script, create_behaviour_script


class ScriptToolsTests(unittest.TestCase):
    def test_create_template_rejects_overwrite_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = create_behaviour_script(root, "scripts/player.py", "PlayerBehaviour")
            self.assertEqual(str(resource), "project://scripts/player.py")
            with self.assertRaises(FileExistsError):
                create_behaviour_script(root, "scripts/player.py", "PlayerBehaviour")
            with self.assertRaises(ValueError):
                create_behaviour_script(root, "../escape.py", "Escape")
            with self.assertRaises(ValueError):
                create_behaviour_script(root, "scripts/class.py", "class")

    def test_attach_rejects_duplicate_but_allows_multiple_classes(self) -> None:
        entity = Entity("Player")
        attach_script(entity, "project://scripts/player.py", "PlayerBehaviour")
        with self.assertRaises(ValueError):
            attach_script(entity, "project://scripts/player.py", "PlayerBehaviour")
        attach_script(entity, "project://scripts/player.py", "HealthBehaviour")
        self.assertEqual(len(entity.components), 2)


if __name__ == "__main__":
    unittest.main()
