"""Tests for the editor command-line entry point (Qt is the only editor frontend)."""

from __future__ import annotations

import subprocess
import sys

import pytest

import expra_engine.main as editor_main


@pytest.fixture
def launched(monkeypatch):
    """Replace the Qt launcher so no real window is created; record how it was called."""
    calls: list[str] = []

    def fake_qt(engine) -> int:
        calls.append("qt")
        return 0

    monkeypatch.setattr("expra_engine.editor.qt.app.run_qt_editor", fake_qt)
    return calls


def test_editor_launches_qt(launched) -> None:
    with pytest.raises(SystemExit) as exit_info:
        editor_main.main([])
    assert exit_info.value.code == 0
    assert launched == ["qt"]


def test_the_exit_code_of_the_qt_editor_is_the_process_exit_code(monkeypatch) -> None:
    monkeypatch.setattr("expra_engine.editor.qt.app.run_qt_editor", lambda engine: 7)
    with pytest.raises(SystemExit) as exit_info:
        editor_main.main([])
    assert exit_info.value.code == 7


@pytest.mark.parametrize("argv", [["--ui", "qt"], ["--ui", "tk"]])
def test_there_is_no_frontend_selection_flag(launched, argv) -> None:
    with pytest.raises(SystemExit) as exit_info:
        editor_main.main(argv)
    assert exit_info.value.code == 2
    assert launched == []


def test_there_is_no_frontend_selection_in_the_entry_point() -> None:
    assert not hasattr(editor_main, "DEFAULT_UI")


def test_missing_pyside6_says_the_install_is_incomplete(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "expra_engine.editor.qt.app", None)  # makes the import fail
    with pytest.raises(SystemExit) as exit_info:
        editor_main.main([])
    message = str(exit_info.value.code)
    assert "PySide6" in message
    assert "required dependency" in message
    assert "pip install PySide6" in message
    assert "Tk" not in message
    assert "[editor]" not in message


def _loaded_gui_roots_after(code: str) -> set[str]:
    script = (
        "import sys;"
        f"{code};"
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'tkinter','ttkbootstrap','_tkinter'}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    return set(eval(result.stdout.strip().splitlines()[-1]))


def test_importing_the_entry_point_does_not_load_tk() -> None:
    assert _loaded_gui_roots_after("import expra_engine.main") == set()
