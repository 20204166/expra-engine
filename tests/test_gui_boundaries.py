"""Hard toolkit boundaries: the editor owns Qt; nothing else imports a GUI toolkit; no Tk anywhere."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from expra_engine.export.manifest import EXCLUDED_DEV_PACKAGES
from expra_engine.export.packager import _is_blocked

SRC = Path(__file__).resolve().parents[1] / "src" / "expra_engine"
ENGINE_LAYERS = ("core", "runtime", "filesystem", "export", "coordinators", "observability")
GUI_ROOTS = {"PySide6", "shiboken6", "PyQt5", "PyQt6", "tkinter", "ttkbootstrap", "_tkinter"}
TK_ROOTS = {"tkinter", "ttkbootstrap", "_tkinter"}


def _imported_roots(path: Path, *, module_level_only: bool = False) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    nodes = tree.body if module_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _python_files(package: str) -> list[Path]:
    root = SRC / package
    if root.is_file():
        return [root]
    if root.with_suffix(".py").is_file():
        return [root.with_suffix(".py")]
    return sorted(root.rglob("*.py")) if root.is_dir() else []


def _offenders(
    paths: Iterable[Path], blocked_roots: set[str], *, module_level_only: bool = False
) -> dict[str, list[str]]:
    """Map each path's label (relative to ``SRC``) to its blocked-root imports."""
    result: dict[str, list[str]] = {}
    for path in paths:
        hits = _imported_roots(path, module_level_only=module_level_only) & blocked_roots
        if hits:
            result[str(path.relative_to(SRC))] = sorted(hits)
    return result


@pytest.mark.parametrize("layer", ENGINE_LAYERS)
def test_engine_layers_import_no_gui_toolkit(layer: str) -> None:
    assert _offenders(_python_files(layer), GUI_ROOTS) == {}


def test_no_module_imports_tk() -> None:
    assert _offenders(sorted(SRC.rglob("*.py")), TK_ROOTS) == {}


def test_shared_editor_core_modules_import_no_gui_toolkit() -> None:
    shared = (
        "editor/window_core.py",
        "editor/inspector_core.py",
        "editor/asset_browser_core.py",
        "editor/viewport_core.py",
        "editor/hierarchy_rows.py",
        "editor/export_dialog_core.py",
        "editor/dialog_provider.py",
        "editor/project_workflow.py",
        "editor/world_authoring.py",
        "editor/script_actions.py",
        "editor/normal_map_actions.py",
        "editor/project_process.py",
        "editor/document_actions.py",
        "coordinators/button_coordinator.py",
    )
    offenders = _offenders((SRC / name for name in shared), GUI_ROOTS, module_level_only=True)
    assert offenders == {}


def _loaded_roots_after_import(module: str) -> set[str]:
    code = (
        "import os, sys; os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen');"
        f"import {module};"
        "print(sorted({m.split('.')[0] for m in sys.modules}))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return set(eval(result.stdout.strip().splitlines()[-1]))


def test_game_runtime_import_closure_has_no_gui_toolkit() -> None:
    loaded = _loaded_roots_after_import("expra_engine.runtime.pygame_renderer")
    assert not (loaded & GUI_ROOTS)
    loaded = _loaded_roots_after_import("expra_engine.export.exporter")
    assert not (loaded & GUI_ROOTS)


def test_qt_editor_process_never_loads_tk() -> None:
    loaded = _loaded_roots_after_import("expra_engine.editor.qt.main_window")
    assert "PySide6" in loaded
    assert not (loaded & {"tkinter", "ttkbootstrap", "_tkinter"})


def test_exports_exclude_the_qt_editor() -> None:
    assert "PySide6" in EXCLUDED_DEV_PACKAGES
    assert _is_blocked("PySide6>=6.7")
    assert _is_blocked("pyside6")
