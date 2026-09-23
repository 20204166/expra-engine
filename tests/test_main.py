"""Tests for the editor command-line entry point."""

from __future__ import annotations

import expra_engine.main as editor_main


def test_main_closes_the_editor_cleanly_on_keyboard_interrupt(monkeypatch) -> None:
    calls: list[str] = []

    class Window:
        def run(self) -> None:
            raise KeyboardInterrupt

        def _on_close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(editor_main, "Engine", lambda: object())
    monkeypatch.setattr(editor_main, "EditorWindow", lambda _engine: Window())

    editor_main.main()

    assert calls == ["close"]
