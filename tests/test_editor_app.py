from __future__ import annotations

import contextlib

from expra_engine.editor import app as editor_app


def test_application_closes_window_on_keyboard_interrupt(monkeypatch) -> None:
    calls: list[str] = []

    class Engine:
        project = object()

    class Window:
        def __init__(self, _engine, *, theme: str) -> None:
            assert theme == "bootstrap-dark"

        def run(self) -> None:
            raise KeyboardInterrupt

        def _on_close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(editor_app, "EditorWindow", Window)
    application = editor_app.EditorApplication(Engine())  # type: ignore[arg-type]

    with contextlib.suppress(KeyboardInterrupt):
        application.run()

    assert calls == ["close"]
