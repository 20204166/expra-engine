from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from expra_engine.core.scene import Scene
from expra_engine.ui.editor_window import EditorWindow


class EditorWindowAutosaveTests(unittest.TestCase):
    def _window(self, tmp_path: Path) -> EditorWindow:
        window = object.__new__(EditorWindow)
        window._root = MagicMock()
        window._is_closing = False
        window._preferences = SimpleNamespace(
            autosave_interval_ms=1234,
            recent_projects=("/one", "/two"),
        )
        window._last_save_path = None
        window._autosave_after_id = None
        window._engine = SimpleNamespace(edit_scene=Scene("Test"))
        window._console = MagicMock()
        return window

    def test_autosave_schedules_and_reschedules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            window._act_save_scene_silent = MagicMock()
            window._root.after.return_value = "timer-1"

            window._start_autosave()
            callback = window._root.after.call_args.args[1]
            callback()

            window._act_save_scene_silent.assert_called_once_with()
            self.assertEqual(window._root.after.call_count, 2)
            self.assertEqual(window._root.after.call_args.args[0], 1234)

    def test_autosave_does_not_reschedule_when_closing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            window._act_save_scene_silent = MagicMock()
            window._root.after.return_value = "timer-1"
            window._start_autosave()
            callback = window._root.after.call_args.args[1]
            window._is_closing = True

            callback()

            self.assertEqual(window._root.after.call_count, 1)

    def test_silent_save_writes_only_when_path_and_scene_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autosave.json"
            window = self._window(Path(directory))
            window._last_save_path = path

            window._act_save_scene_silent()

            self.assertEqual(json.loads(path.read_text()), window._engine.edit_scene.to_dict())

            path.unlink()
            window._last_save_path = None
            window._act_save_scene_silent()
            self.assertFalse(path.exists())


class RecentProjectsMenuTests(unittest.TestCase):
    def test_populate_recent_projects_uses_disabled_placeholder_when_empty(self) -> None:
        window = object.__new__(EditorWindow)
        window._recent_menu = MagicMock()
        window._preferences = SimpleNamespace(recent_projects=())

        window._populate_recent_projects()

        window._recent_menu.add_command.assert_called_once_with(label="(none)", state="disabled")


if __name__ == "__main__":
    unittest.main()
