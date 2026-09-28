"""Shared editor conversion from filesystem paths to project-relative paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from expra_engine.editor.project_paths import (
    project_relative_path,
    resolved_project_relative_path,
)


def test_project_relative_path_returns_path_relative_to_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    candidate = root / "scenes" / "main.scene.pb"

    assert project_relative_path(root, candidate) == Path("scenes/main.scene.pb")


def test_project_relative_path_rejects_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(ValueError):
        project_relative_path(root, tmp_path / "outside.scene.pb")


def test_project_relative_path_rejects_resolved_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.scene.pb"
    outside.write_text("outside")
    link = root / "escape.scene.pb"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    with pytest.raises(ValueError):
        resolved_project_relative_path(root, link)
