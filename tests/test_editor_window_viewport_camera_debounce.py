"""Regression tests for the viewport-camera preferences-write debounce.

Section 11 of the Tk smoothness pass: _save_viewport_camera used to call
PreferencesStore.save() (an atomic write + fsync, measured ~4-8ms) on every
single pan-motion/wheel-zoom event -- a sustained drag could fire dozens of
synchronous disk writes per second on the Tk main thread. It now updates the
in-memory value immediately but debounces the actual write, and _on_close
flushes any write still pending so the final camera state is never lost.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, call

from expra_engine.editor.preferences import EditorPreferences
from expra_engine.ui.editor_window import EditorWindow


def _window() -> EditorWindow:
    window = object.__new__(EditorWindow)
    window._preferences = EditorPreferences()
    window._preferences_store = MagicMock()
    window._preferences_path = Path("/fake/preferences.json")
    window._viewport_camera_save_after_id = None
    window._timer = MagicMock()
    return window


class ViewportCameraDebounceTests(unittest.TestCase):
    def test_rapid_camera_changes_do_not_write_to_disk_immediately(self) -> None:
        window = _window()
        window._timer.schedule.side_effect = ["t1", "t2", "t3"]

        window._save_viewport_camera({"x": 1.0})
        window._save_viewport_camera({"x": 2.0})
        window._save_viewport_camera({"x": 3.0})

        window._preferences_store.save.assert_not_called()
        self.assertEqual(window._preferences.viewport_camera, {"x": 3.0})

    def test_each_change_cancels_the_previous_pending_timer(self) -> None:
        window = _window()
        window._timer.schedule.side_effect = ["t1", "t2", "t3"]

        window._save_viewport_camera({"x": 1.0})
        window._save_viewport_camera({"x": 2.0})
        window._save_viewport_camera({"x": 3.0})

        self.assertEqual(
            window._timer.cancel.call_args_list, [call(None), call("t1"), call("t2")]
        )

    def test_debounced_flush_writes_once_with_the_latest_value(self) -> None:
        window = _window()
        window._timer.schedule.return_value = "t1"

        window._save_viewport_camera({"x": 1.0})
        window._save_viewport_camera({"x": 2.0})
        window._save_viewport_camera({"x": 3.0})

        flush_callback = window._timer.schedule.call_args.args[1]
        flush_callback()

        window._preferences_store.save.assert_called_once_with(
            window._preferences_path, window._preferences
        )
        self.assertEqual(window._preferences.viewport_camera, {"x": 3.0})
        self.assertIsNone(window._viewport_camera_save_after_id)


class ViewportCameraCloseFlushTests(unittest.TestCase):
    def _closing_window(self) -> EditorWindow:
        window = _window()
        window._runtime_preview = MagicMock()
        window._is_closing = False
        window._autosave_after_id = None
        window._sash_after_id = None
        window._root = MagicMock()
        window._root.geometry.return_value = ""  # -> WindowGeometry parses to None
        window._contributions = MagicMock()
        window._delivery_queue = MagicMock()
        window._coordinator = MagicMock()
        window._ui = MagicMock()
        return window

    def test_on_close_flushes_a_still_pending_camera_write(self) -> None:
        window = self._closing_window()
        window._viewport_camera_save_after_id = "pending-timer"
        window._preferences = EditorPreferences(viewport_camera={"x": 9.0})

        window._on_close()

        window._timer.cancel.assert_any_call("pending-timer")
        window._preferences_store.save.assert_called_once_with(
            window._preferences_path, window._preferences
        )
        self.assertIsNone(window._viewport_camera_save_after_id)

    def test_on_close_does_not_write_when_nothing_is_pending(self) -> None:
        window = self._closing_window()
        window._viewport_camera_save_after_id = None

        window._on_close()

        window._preferences_store.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
