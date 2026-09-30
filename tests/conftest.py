"""Shared isolation for tests that construct the real editor window."""

from __future__ import annotations

import importlib

import pytest

from tests.support.qt_editor import QtEditorHarness


@pytest.fixture(autouse=True)
def isolate_real_editor_preferences(request: pytest.FixtureRequest) -> None:
    """Keep temporary editor projects out of the human preferences file."""
    editor_module = importlib.import_module("expra_engine.editor.qt.main_window")
    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(editor_module, "DEFAULT_PREFERENCES_PATH", tmp_path / "preferences.json")


@pytest.fixture
def frontend(tmp_path):
    """Headless Qt editor harness (window factory + widget probes)."""
    return QtEditorHarness(tmp_path / "preferences.json")


@pytest.fixture
def window(frontend):
    """Factory for shown editor windows; every window is closed at teardown."""
    created = []

    def make(engine=None):
        w = frontend.make(engine)
        created.append(w)
        frontend.pump(w)
        return w

    yield make
    for w in created:
        if not w._is_closing:
            frontend.close(w)
