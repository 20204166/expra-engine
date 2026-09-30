"""Linux/X11 startup diagnostic for the Qt frontend.

Qt's ``xcb`` platform plugin links system libraries that PySide6 does not ship
(notably ``libxcb-cursor0``). When one is missing, Qt aborts inside
``QApplication`` with a core dump and no useful message. Before creating the
application, load the xcb plugin ourselves and turn the loader's error into an
instruction. Linux only, and only when xcb is the platform Qt will use; other
platforms and Wayland/offscreen sessions are never checked.
"""

from __future__ import annotations

import ctypes
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_KNOWN_LIBRARIES = {
    "libxcb-cursor.so.0": (
        "Debian/Ubuntu: sudo apt install libxcb-cursor0\n"
        "  Fedora:        sudo dnf install xcb-util-cursor\n"
        "  Arch:          sudo pacman -S xcb-util-cursor"
    ),
}


def xcb_plugin_path() -> Path | None:
    """Location of PySide6's ``libqxcb.so`` platform plugin, if it exists."""
    from PySide6.QtCore import QLibraryInfo

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    path = plugins / "platforms" / "libqxcb.so"
    return path if path.is_file() else None


def _load_xcb_plugin() -> None:
    path = xcb_plugin_path()
    if path is not None:
        ctypes.CDLL(str(path))


def _xcb_will_be_used(environ: Mapping[str, str]) -> bool:
    requested = [name.strip().lower() for name in environ.get("QT_QPA_PLATFORM", "").split(";") if name.strip()]
    if requested:
        return requested[0].split(":")[0] == "xcb"
    return not (environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or environ.get("WAYLAND_DISPLAY"))


def _describe(error: OSError) -> str:
    text = str(error)
    match = re.search(r"(lib[\w+.-]+\.so[\w.]*): cannot open shared object file", text)
    if match is None:
        return f"Qt's X11 (xcb) platform plugin could not be loaded: {text}"
    library = match.group(1)
    install = _KNOWN_LIBRARIES.get(
        library,
        f"install the system package that provides {library} (search your distribution's packages)",
    )
    return (
        f"Qt's X11 (xcb) platform plugin cannot load because a system library is missing: {library}.\n"
        f"Install it, then start the editor again:\n  {install}"
    )


def qt_startup_problem(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    plugin_loader: Callable[[], Any] | None = None,
) -> str | None:
    """Return an actionable message if Qt cannot start on this machine, else ``None``."""
    if not (platform if platform is not None else sys.platform).startswith("linux"):
        return None
    if not _xcb_will_be_used(environ if environ is not None else _process_environ()):
        return None
    try:
        (plugin_loader or _load_xcb_plugin)()
    except OSError as error:
        return _describe(error)
    return None


def _process_environ() -> Mapping[str, str]:
    import os

    return os.environ


__all__ = ["qt_startup_problem", "xcb_plugin_path"]
