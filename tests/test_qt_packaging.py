"""Packaging policy: PySide6 is a REQUIRED dependency of the editor install, never of a game.

Qt is the default editor frontend, so a normal ``pip install``/installer run must bring PySide6
with it (no optional extra to discover). Exported games are built from an explicit runtime package
list and a staged module whitelist, so the editor's dependencies must never reach them.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from expra_engine.export.manifest import EXCLUDED_DEV_PACKAGES
from expra_engine.export.packager import _is_blocked

ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _names(requirements: list[str]) -> set[str]:
    return {re.split(r"[<>=!~;\[\s]", item, maxsplit=1)[0].lower().replace("_", "-") for item in requirements}


def test_pyside6_is_a_required_dependency() -> None:
    assert "pyside6" in _names(_project()["dependencies"])


def test_there_is_no_separate_editor_extra_to_discover() -> None:
    extras = _project().get("optional-dependencies", {})
    assert "editor" not in extras
    for requirements in extras.values():
        assert "pyside6" not in _names(requirements)


def test_no_tk_dependency_is_declared() -> None:
    project = _project()
    declared = set(_names(project["dependencies"]))
    for requirements in project.get("optional-dependencies", {}).values():
        declared |= set(_names(requirements))
    assert not declared & {"ttkbootstrap", "tkinter"}


def test_docs_do_not_send_users_to_a_removed_extra() -> None:
    for name in ("README.md", "tools/expra_mcp/README.md"):
        assert "[editor]" not in (ROOT / name).read_text(encoding="utf-8"), name


def test_smoke_installer_proves_qt_comes_with_a_normal_install() -> None:
    script = (ROOT / "scripts" / "smoke-installed-editor.sh").read_text(encoding="utf-8")
    assert "PySide6" in script
    assert "expra_engine.editor.qt" in script


def test_export_blocks_the_whole_pyside6_family() -> None:
    for package in ("PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "PySide6>=6.7"):
        assert _is_blocked(package), package
    assert "PySide6" in EXCLUDED_DEV_PACKAGES


def test_a_runtime_export_never_installs_or_stages_the_editor_toolkit(tmp_path) -> None:
    from expra_engine.export.exporter import _runtime_packages, _stage_pygame_runtime
    from expra_engine.export.plan import ExportPlan, ExportTarget, RuntimeProfile

    (tmp_path / "__main__.py").write_text("print('game')\n", encoding="utf-8")
    plan = ExportPlan(
        project_dir=tmp_path,
        entry_point="__main__.py",
        output_dir=tmp_path / "out",
        target=ExportTarget("linux"),
        game_name="g",
        game_version="1.0",
        python_version="3.12.4",
        runtime_profile=RuntimeProfile.PYGAME,
    )
    assert not any("pyside" in p.lower() or "shiboken" in p.lower() for p in _runtime_packages(plan))

    _stage_pygame_runtime(tmp_path / "site")
    staged = tmp_path / "site" / "expra_engine"
    assert not (staged / "editor").exists()
    assert not (staged / "ui").exists()
    offenders = [
        str(path.relative_to(staged))
        for path in staged.rglob("*.py")
        if re.search(r"^\s*(import|from)\s+(PySide6|shiboken6|tkinter|ttkbootstrap)\b", path.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == []
