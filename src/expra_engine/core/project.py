"""Project — file structure and scene registry.

A Project points to a directory on disk:
    project/
        project.json
        scenes/
        assets/

It does not own file I/O directly. ``ProjectIO`` handles reading and writing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from expra_engine.core.scene import Scene


class Project:
    """File-backed collection of scenes and assets.

    The project is light: it holds metadata and a list of known scene
    file paths. Scenes are loaded on demand, not kept all in memory.
    """

    def __init__(
        self,
        name: str,
        path: Path,
    ) -> None:
        self.name = name
        self.path = path
        self._scene_paths: list[str] = []
        self._active_scene: Scene | None = None

    @property
    def scenes_dir(self) -> Path:
        return self.path / "scenes"

    @property
    def assets_dir(self) -> Path:
        return self.path / "assets"

    @property
    def project_file(self) -> Path:
        return self.path / "project.json"

    @property
    def active_scene(self) -> Scene | None:
        return self._active_scene

    def set_active_scene(self, scene: Scene | None) -> None:
        self._active_scene = scene

    def register_scene_path(self, relative_path: str) -> None:
        if relative_path not in self._scene_paths:
            self._scene_paths.append(relative_path)

    def scene_paths(self) -> tuple[str, ...]:
        return tuple(self._scene_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scenes": list(self._scene_paths),
        }

    def save(self) -> None:
        """Write project.json to disk. Creates directories if needed."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(exist_ok=True)
        self.assets_dir.mkdir(exist_ok=True)
        self.project_file.write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> Project:
        """Load a project from its directory. ``path`` must contain project.json."""
        project_file = path / "project.json"
        data = json.loads(project_file.read_text(encoding="utf-8"))
        project = cls(name=str(data["name"]), path=path)
        for scene_path in data.get("scenes", []):
            project.register_scene_path(str(scene_path))
        return project

    @classmethod
    def create(cls, name: str, path: Path) -> Project:
        """Create a new project at ``path``, writing initial project.json."""
        project = cls(name=name, path=path)
        project.save()
        return project

    def __repr__(self) -> str:
        return f"Project({self.name!r}, path={self.path})"
