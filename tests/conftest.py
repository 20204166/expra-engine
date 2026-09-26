"""Shared isolation for tests that construct the real editor window."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_real_editor_preferences(request: pytest.FixtureRequest) -> None:
    """Keep temporary editor projects out of the human preferences file."""
    editor_module = sys.modules.get("expra_engine.ui.editor_window")
    if editor_module is None or getattr(request.module, "EditorWindow", None) is None:
        return
    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(editor_module, "_PREFERENCES_PATH", tmp_path / "preferences.json")
