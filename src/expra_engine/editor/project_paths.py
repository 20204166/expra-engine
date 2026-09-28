"""Project-relative path conversion shared by editor workflows."""

from __future__ import annotations

from pathlib import Path


def project_relative_path(project_root: Path, path: Path) -> Path:
    """Return ``path`` relative to ``project_root`` without resolving either."""
    return path.relative_to(project_root)


def resolved_project_relative_path(project_root: Path, path: Path) -> Path:
    """Resolve both paths, then return the candidate path relative to the root."""
    return project_relative_path(project_root.resolve(), path.resolve())
