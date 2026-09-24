"""Project — file structure and scene registry.

A Project points to a directory on disk:
    project/
        project.json
        scenes/
        assets/

It does not own file I/O directly. ``ProjectIO`` handles reading and writing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from expra_engine.core.persistence import atomic_write_text
from expra_engine.core.scene import Scene

if TYPE_CHECKING:
    from expra_engine.filesystem import ResourceService
from expra_engine.filesystem import ResourceId

CURRENT_SCHEMA_VERSION = 1


class ProjectError(ValueError):
    """Raised when a project cannot be safely created or loaded."""


class Project:
    """File-backed collection of scenes and assets.

    The project is light: it holds metadata and a list of known scene
    file paths. Scenes are loaded on demand, not kept all in memory.
    """

    def __init__(
        self,
        name: str,
        path: Path,
        *,
        game_version: str = "0.1.0",
        start_scene: str | None = None,
        schema_version: int = CURRENT_SCHEMA_VERSION,
        input_settings: dict[str, str] | None = None,
        entry_point: str = "__main__.py",
    ) -> None:
        self.name = str(name)
        self.path = path.resolve()
        self.game_version = game_version
        self._start_scene = start_scene
        self.schema_version = schema_version
        self.input_settings = dict(input_settings or {})
        self.entry_point = entry_point
        self._scene_paths: list[str] = []
        self._active_scene: Scene | None = None

    @property
    def scenes_dir(self) -> Path:
        scene_paths = (self.start_scene, *self._scene_paths)
        folder = "scene" if any(
            isinstance(value, str) and value.startswith("scene/") for value in scene_paths
        ) else "scenes"
        return self.path / folder

    @property
    def assets_dir(self) -> Path:
        return self.path / "assets"

    @property
    def scripts_dir(self) -> Path:
        return self.path / "scripts"

    @property
    def root(self) -> Path:
        return self.path

    @property
    def start_scene(self) -> str | None:
        return self._start_scene

    def set_start_scene(self, relative_path: str) -> None:
        self._validate_scene_path(relative_path)
        self._start_scene = relative_path

    def asset_id(self, path: str | Path) -> ResourceId:
        """Return the stable logical ID for an asset path.

        Relative paths are relative to the project's assets directory. Absolute
        paths are accepted only when they point inside that directory.
        """

        asset_path = Path(path)
        if asset_path.is_absolute():
            try:
                asset_path = asset_path.resolve().relative_to(self.assets_dir.resolve())
            except ValueError:
                return ResourceId.from_project_path(asset_path)
        return ResourceId.from_project_path(asset_path)

    def import_asset(self, source: Path, relative_path: str | None = None) -> ResourceId:
        """Copy one external asset into ``assets/`` without overwriting files."""
        source = source.expanduser().resolve()
        if not source.is_file():
            raise ProjectError(f"asset source is not a file: {source}")
        relative = Path(relative_path or source.name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ProjectError("asset destination must remain inside assets/")
        destination = (self.assets_dir / relative).resolve()
        try:
            destination.relative_to(self.assets_dir.resolve())
        except ValueError as exc:
            raise ProjectError("asset destination escapes assets/") from exc
        if destination.exists():
            raise ProjectError(f"asset already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(
                prefix=".expra-import-", dir=destination.parent
            )
            os.close(descriptor)
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            temporary = None
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
        return ResourceId.from_project_path(relative)

    def set_input_binding(self, action: str, physical: str) -> None:
        """Set one serialized semantic input binding."""
        if not action.strip() or ":" not in physical or not all(physical.split(":", 1)):
            raise ProjectError("input binding must look like keyboard:left")
        self.input_settings[action.strip()] = physical.strip().lower()

    def resource_service(self, *, observer: Any | None = None) -> ResourceService:
        """Build a renderer-neutral service for this project's assets."""
        from expra_engine.filesystem import (
            DirectoryMount,
            MountSpec,
            ResourceResolver,
            ResourceService,
        )

        mount = DirectoryMount(
            self.assets_dir,
            MountSpec(name="project-assets", scheme="assets", read_only=False),
        )
        project_mount = DirectoryMount(
            self.path,
            MountSpec(name="project-files", scheme="project", read_only=True),
        )
        return ResourceService(ResourceResolver([mount, project_mount]), observer=observer)

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

    def scene_file(self, relative_path: str | None = None) -> Path:
        """Return a validated project-owned scene file path."""
        value = relative_path or self.start_scene
        if value is None:
            raise ProjectError("project has no start scene")
        self._validate_scene_path(value)
        path = (self.path / value).resolve()
        try:
            path.relative_to(self.path)
        except ValueError as exc:
            raise ProjectError(f"scene escapes project: {value!r}") from exc
        return path

    def load_scene(self, relative_path: str | None = None) -> Scene:
        try:
            scene = Scene.from_dict(
                json.loads(self.scene_file(relative_path).read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ProjectError("could not load project scene") from exc
        self.set_active_scene(scene)
        return scene

    def save_scene(self, scene: Scene, relative_path: str | None = None) -> Path:
        path = self.scene_file(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(scene.to_dict(), indent=2))
        value = relative_path or self.start_scene
        if value is not None:
            self.register_scene_path(value)
        return path

    def scene_paths(self) -> tuple[str, ...]:
        return tuple(self._scene_paths)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "game_version": self.game_version,
            "scenes": list(self._scene_paths),
        }
        if self._start_scene is not None:
            data["start_scene"] = self._start_scene
        if self.input_settings:
            data["input"] = dict(self.input_settings)
        if self.entry_point != "__main__.py":
            data["entry_point"] = self.entry_point
        return data

    def save(self) -> None:
        """Write project.json to disk. Creates directories if needed."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(exist_ok=True)
        self.assets_dir.mkdir(exist_ok=True)
        self.scripts_dir.mkdir(exist_ok=True)
        atomic_write_text(self.project_file, json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> Project:
        """Load a project from its directory. ``path`` must contain project.json."""
        root = path.resolve() if path.is_dir() else path.parent.resolve()
        project_file = root / "project.json"
        try:
            data = json.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ProjectError(f"could not read project manifest: {project_file}") from exc
        if not isinstance(data, dict):
            raise ProjectError("project manifest must contain an object")
        schema_version = int(data.get("schema_version", 0))
        if schema_version > CURRENT_SCHEMA_VERSION:
            raise ProjectError(f"unsupported future project schema: {schema_version}")
        name = data.get("name")
        scenes = data.get("scenes", [])
        if not isinstance(name, str) or not name.strip() or not isinstance(scenes, list):
            raise ProjectError("project manifest has invalid name or scenes")
        start_scene = data.get("start_scene")
        if start_scene is not None and not isinstance(start_scene, str):
            raise ProjectError("project start_scene must be a string")
        input_settings = data.get("input", {})
        if not isinstance(input_settings, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in input_settings.items()
        ):
            raise ProjectError("project input settings must be a string mapping")
        if any(
            ":" not in value or not all(value.split(":", 1)) for value in input_settings.values()
        ):
            raise ProjectError("project input bindings must look like keyboard:left")
        entry_point = data.get("entry_point", "__main__.py")
        if (
            not isinstance(entry_point, str)
            or Path(entry_point).is_absolute()
            or ".." in Path(entry_point).parts
        ):
            raise ProjectError("project entry_point must be project-relative")
        project = cls(
            name=name,
            path=root,
            game_version=str(data.get("game_version", "0.1.0")),
            start_scene=start_scene,
            schema_version=schema_version,
            input_settings=input_settings,
            entry_point=entry_point,
        )
        for scene_path in scenes:
            if not isinstance(scene_path, str):
                raise ProjectError("project scene paths must be strings")
            project._validate_scene_path(scene_path)
            project.register_scene_path(scene_path)
        if project.start_scene is not None:
            project._validate_scene_path(project.start_scene)
        if project.start_scene is None and project.scene_paths():
            project._start_scene = project.scene_paths()[0]
        for directory in (project.scenes_dir, project.assets_dir, project.scripts_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return project

    @classmethod
    def create(cls, name: str, path: Path) -> Project:
        """Create a new project at ``path``, writing initial project.json."""
        cls._validate_name(name)
        destination = path.expanduser()
        if destination.is_symlink():
            raise ProjectError("project destination cannot be a symlink")
        if destination.exists() and any(destination.iterdir()):
            raise ProjectError(f"project destination is not empty: {destination}")
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        if any((ancestor / "project.json").is_file() for ancestor in (parent, *parent.parents)):
            raise ProjectError("project cannot be created inside another project")
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
        try:
            project = cls(
                name=name,
                path=stage,
                game_version="0.1.0",
                start_scene="scenes/main.json",
            )
            project.register_scene_path("scenes/main.json")
            project.save()
            (stage / "scenes" / "main.json").write_text(
                json.dumps(Scene("Main").to_dict(), indent=2) + "\n", encoding="utf-8"
            )
            (stage / "__main__.py").write_text(
                "from expra_engine.runtime.project_runner import run_project\n\n"
                'if __name__ == "__main__":\n'
                "    run_project()\n",
                encoding="utf-8",
            )
            if destination.exists():
                destination.rmdir()
            os.replace(stage, destination)
            return cls.load(destination)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ProjectError("project name cannot be blank")
        if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
            raise ProjectError("project name must be a single safe directory name")

    @staticmethod
    def _validate_scene_path(relative_path: str) -> None:
        candidate = Path(relative_path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or not any(relative_path.startswith(prefix) for prefix in ("scenes/", "scene/"))
        ):
            raise ProjectError(
                f"scene must be project-relative under scene/ or scenes/: {relative_path!r}"
            )

    def __repr__(self) -> str:
        return f"Project({self.name!r}, path={self.path})"
