"""Tests for EditorPreferences and PreferencesStore."""

import json
import tempfile
import unittest
from pathlib import Path

from expra_engine.editor.preferences import EditorPreferences, PreferencesStore


class EditorPreferencesTests(unittest.TestCase):
    def test_defaults(self) -> None:
        prefs = EditorPreferences()
        self.assertEqual(prefs.theme, "darkly")
        self.assertEqual(prefs.recent_projects, ())
        self.assertEqual(prefs.autosave_interval_ms, 30_000)
        self.assertEqual(prefs.schema_version, 1)

    def test_is_frozen(self) -> None:
        prefs = EditorPreferences()
        with self.assertRaises((AttributeError, TypeError)):
            prefs.theme = "something"  # type: ignore[misc]


class PreferencesStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PreferencesStore()

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            prefs = EditorPreferences(theme="litera", recent_projects=("/a", "/b"))
            self.store.save(path, prefs)
            loaded = self.store.load(path)
            self.assertEqual(loaded.theme, "litera")
            self.assertEqual(loaded.recent_projects, ("/a", "/b"))

    def test_viewport_camera_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            state = {"position": [2.0, 3.0], "zoom": 2.0, "rotation": 0.5}
            self.store.save(path, EditorPreferences(viewport_camera=state))

            self.assertEqual(self.store.load(path).viewport_camera, state)

    def test_invalid_viewport_camera_state_falls_back_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            path.write_text(
                json.dumps({"schema_version": 1, "viewport_camera": []}), encoding="utf-8"
            )

            self.assertEqual(self.store.load(path).viewport_camera, {})

    def test_load_missing_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nonexistent.json"
            prefs = self.store.load(path)
            self.assertEqual(prefs, EditorPreferences())

    def test_load_malformed_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            path.write_text("not json {{{", encoding="utf-8")
            prefs = self.store.load(path)
            self.assertEqual(prefs, EditorPreferences())

    def test_load_wrong_schema_version_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            path.write_text(json.dumps({"schema_version": 99, "theme": "darkly"}), encoding="utf-8")
            prefs = self.store.load(path)
            self.assertEqual(prefs, EditorPreferences())

    def test_load_non_dict_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            prefs = self.store.load(path)
            self.assertEqual(prefs, EditorPreferences())

    def test_save_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "dir" / "prefs.json"
            self.store.save(path, EditorPreferences())
            self.assertTrue(path.exists())

    def test_recent_projects_preserved_as_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            prefs = EditorPreferences(recent_projects=("/game1", "/game2", "/game3"))
            self.store.save(path, prefs)
            loaded = self.store.load(path)
            self.assertIsInstance(loaded.recent_projects, tuple)
            self.assertEqual(loaded.recent_projects, ("/game1", "/game2", "/game3"))

    def test_window_geometry_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.json"
            self.store.save(path, EditorPreferences(window_geometry="1280x800+10+20"))
            loaded = self.store.load(path)
            self.assertEqual(loaded.window_geometry, "1280x800+10+20")


if __name__ == "__main__":
    unittest.main()
