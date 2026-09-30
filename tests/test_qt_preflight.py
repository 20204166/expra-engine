"""Linux/X11 startup diagnostic: Qt's xcb platform plugin needs system libraries (libxcb-cursor0).

Without them Qt aborts inside QApplication with a core dump. The preflight tries to load the xcb
plugin first and turns the loader's error into an actionable message. It is Linux-only and lives
in the Qt frontend, never in core/runtime.
"""

from __future__ import annotations

import pytest

from expra_engine.editor.qt.preflight import qt_startup_problem

MISSING = OSError("libxcb-cursor.so.0: cannot open shared object file: No such file or directory")


def _loader_raising(error: Exception):
    def load() -> None:
        raise error

    return load


def _ok() -> None:
    return None


def test_missing_xcb_cursor_gives_an_actionable_message() -> None:
    message = qt_startup_problem(
        environ={"DISPLAY": ":0"}, platform="linux", plugin_loader=_loader_raising(MISSING)
    )
    assert message is not None
    assert "libxcb-cursor0" in message
    assert "apt install libxcb-cursor0" in message
    assert "dnf install xcb-util-cursor" in message
    assert "pacman -S xcb-util-cursor" in message
    assert "--ui" not in message
    assert "Tk" not in message


def test_explicit_xcb_platform_is_checked_even_without_display_hints() -> None:
    message = qt_startup_problem(
        environ={"QT_QPA_PLATFORM": "xcb"}, platform="linux", plugin_loader=_loader_raising(MISSING)
    )
    assert message is not None and "libxcb-cursor0" in message


def test_an_unknown_missing_library_is_named_verbatim() -> None:
    error = OSError("libxcb-icccm.so.4: cannot open shared object file: No such file or directory")
    message = qt_startup_problem(
        environ={"DISPLAY": ":0"}, platform="linux", plugin_loader=_loader_raising(error)
    )
    assert message is not None
    assert "libxcb-icccm.so.4" in message
    assert "--ui" not in message
    assert "Tk" not in message


def test_a_plugin_that_loads_is_fine() -> None:
    assert qt_startup_problem(environ={"DISPLAY": ":0"}, platform="linux", plugin_loader=_ok) is None


@pytest.mark.parametrize("platform", ["win32", "darwin", "cygwin"])
def test_non_linux_platforms_never_run_the_linux_check(platform: str) -> None:
    def explode() -> None:
        raise AssertionError("the Linux plugin check must not run here")

    assert qt_startup_problem(environ={"DISPLAY": ":0"}, platform=platform, plugin_loader=explode) is None


@pytest.mark.parametrize(
    "environ",
    [
        {"QT_QPA_PLATFORM": "offscreen"},
        {"QT_QPA_PLATFORM": "minimal"},
        {"QT_QPA_PLATFORM": "wayland"},
        {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
        {"WAYLAND_DISPLAY": "wayland-0"},
    ],
)
def test_platforms_that_do_not_use_xcb_are_not_checked(environ) -> None:
    def explode() -> None:
        raise AssertionError("xcb is not the selected platform")

    assert qt_startup_problem(environ=environ, platform="linux", plugin_loader=explode) is None


def test_the_default_loader_knows_where_the_real_xcb_plugin_lives() -> None:
    import sys

    if not sys.platform.startswith("linux"):
        pytest.skip("Linux only")
    from expra_engine.editor.qt.preflight import xcb_plugin_path

    path = xcb_plugin_path()
    assert path is not None and path.name == "libqxcb.so" and path.is_file()


def test_run_qt_editor_stops_before_creating_the_application(monkeypatch) -> None:
    import expra_engine.editor.qt.app as app_module

    created: list[str] = []
    monkeypatch.setattr(app_module, "qt_startup_problem", lambda: "BOOM: install libxcb-cursor0")
    monkeypatch.setattr(
        app_module.QApplication, "instance", staticmethod(lambda: created.append("instance"))
    )
    with pytest.raises(SystemExit) as exit_info:
        app_module.run_qt_editor(object())  # type: ignore[arg-type]
    assert "BOOM" in str(exit_info.value.code)
    assert created == []


def test_the_mcp_editor_worker_reports_the_same_diagnostic(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools/expra_mcp/src/expra_dev_mcp/_editor_worker.py"
    spec = importlib.util.spec_from_file_location("editor_worker_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("expra_engine.editor.qt.preflight.qt_startup_problem", lambda **_k: "BOOM: libxcb-cursor0")
    with pytest.raises(RuntimeError, match="libxcb-cursor0"):
        module._QtShell().create(object(), Path("/nonexistent/prefs.json"))
