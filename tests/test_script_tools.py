import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expra_engine.core.entity import Entity
from expra_engine.editor.script_tools import (
    _is_behaviour_script_resource,
    attach_script,
    create_behaviour_script,
)
from expra_engine.filesystem import ResourceId


class ScriptToolsTests(unittest.TestCase):
    def test_behaviour_script_resource_policy_is_shared(self) -> None:
        self.assertTrue(_is_behaviour_script_resource(ResourceId.parse("project://scripts/player.py")))
        self.assertFalse(_is_behaviour_script_resource(ResourceId.parse("assets://scripts/player.py")))
        self.assertFalse(_is_behaviour_script_resource(ResourceId.parse("project://assets/player.py")))
        self.assertFalse(_is_behaviour_script_resource(ResourceId.parse("project://scripts/player.txt")))

    def test_create_and_attach_both_use_the_shared_resource_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "expra_engine.editor.script_tools._is_behaviour_script_resource",
            return_value=False,
            create=True,
        ):
            with self.assertRaisesRegex(ValueError, "project://scripts/\\*.py"):
                create_behaviour_script(Path(directory), "scripts/player.py", "Player")
            with self.assertRaisesRegex(ValueError, "project://scripts/\\*.py"):
                attach_script(Entity("Player"), "project://scripts/player.py", "Player")

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

    def test_create_rejects_non_string_class_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for bad in (42, None, ["PlayerBehaviour"]):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    create_behaviour_script(root, "scripts/player.py", bad)

    def test_attach_rejects_non_string_class_name(self) -> None:
        entity = Entity("Player")
        for bad in (42, None, ["PlayerBehaviour"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                attach_script(entity, "project://scripts/player.py", bad)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable on this platform")
    def test_create_rejects_symlink_directory_escape(self) -> None:
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as inside:
            root = Path(inside)
            (root / "scripts").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaises(ValueError):
                create_behaviour_script(root, "scripts/player.py", "PlayerBehaviour")


if __name__ == "__main__":
    unittest.main()
