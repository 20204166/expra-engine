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

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.persistence import atomic_write_bytes, atomic_write_text
from expra_engine.core.scene import (
    Level,
    Scene,
    SceneInstanceComponent,
    resolve_scene_instances,
)
from expra_engine.core.scene.document_codec import (
    DocumentCodecError,
    decode_json_payload,
    encode_protobuf,
    from_json,
    kind_for_document_path,
    parse_protobuf,
    protobuf_to_document_data,
)
from expra_engine.observability import ObservabilityWatcher

if TYPE_CHECKING:
    from expra_engine.filesystem import ResourceService
from expra_engine.filesystem import ResourceId

CURRENT_SCHEMA_VERSION = 1


class ProjectError(ValueError):
    """Raised when a project cannot be safely created or loaded."""


@contextlib.contextmanager
def _observe_stage(observer: ObservabilityWatcher | None, target: str):
    """Record one bounded document-load stage when a host supplies a watcher."""
    if observer is None:
        yield
        return
    token = observer.begin(target)
    try:
        yield
    except Exception as exc:
        observer.finish(token, outcome="failure", detail=f"{type(exc).__name__}: {exc}")
        raise
    else:
        observer.finish(token)


def _apply_expected_document_kind(data: dict[str, Any], expected_kind: DocumentKind | None) -> None:
    if expected_kind is None:
        return
    stored_kind = data.get("kind")
    if stored_kind is None:
        data["kind"] = expected_kind.value
    elif stored_kind != expected_kind.value:
        raise DocumentCodecError(
            f"expected a {expected_kind.value} document, found {stored_kind!r}"
        )


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
        entrypoint: str | None = None,
        script_entry_point: str | None = None,
        level_paths: list[str] | None = None,
    ) -> None:
        self.name = str(name)
        self.path = path.resolve()
        self.game_version = game_version
        if entrypoint is not None and start_scene is not None and entrypoint != start_scene:
            raise ProjectError("entrypoint conflicts with legacy start_scene")
        self._entrypoint = entrypoint if entrypoint is not None else start_scene
        self.schema_version = schema_version
        self.input_settings = dict(input_settings or {})
        self.script_entry_point = (
            script_entry_point if script_entry_point is not None else entry_point
        )
        self._scene_paths: list[str] = []
        self._level_paths: list[str] = list(level_paths or [])
        self._active_scene: Scene | None = None

    @property
    def scenes_dir(self) -> Path:
        scene_paths = (self.start_scene, *self._scene_paths)
        folder = (
            "scene"
            if any(isinstance(value, str) and value.startswith("scene/") for value in scene_paths)
            else "scenes"
        )
        return self.path / folder

    @property
    def levels_dir(self) -> Path:
        return self.path / "levels"

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
        return self._entrypoint

    @property
    def entrypoint(self) -> str | None:
        """Canonical project-relative Scene/Level resource entrypoint."""
        return self._entrypoint

    @property
    def entry_point(self) -> str:
        """Compatibility alias for the Python script launcher."""
        return self.script_entry_point

    @entry_point.setter
    def entry_point(self, value: str) -> None:
        self.script_entry_point = value

    def set_start_scene(self, relative_path: str) -> None:
        self._validate_scene_path(relative_path)
        self._entrypoint = relative_path

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
        self._validate_scene_path(relative_path)
        if relative_path not in self._scene_paths:
            self._scene_paths.append(relative_path)

    def register_level_path(self, relative_path: str) -> None:
        """Register a project-relative Level document path."""
        self._validate_level_path(relative_path)
        if relative_path not in self._level_paths:
            self._level_paths.append(relative_path)

    def level_paths(self) -> tuple[str, ...]:
        return tuple(self._level_paths)

    def scene_file(self, relative_path: str | None = None) -> Path:
        """Return a validated Scene resource path (legacy JSON or typed PB)."""
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

    def document_file(self, relative_path: str | None = None) -> Path:
        """Return a validated project-owned Scene/Level document path."""
        value = relative_path or self.entrypoint
        if value is None:
            raise ProjectError("project has no document entrypoint")
        self._validate_entrypoint(value)
        path = (self.path / value).resolve()
        try:
            path.relative_to(self.path)
        except ValueError as exc:
            raise ProjectError(f"document escapes project: {value!r}") from exc
        return path

    def load_document(
        self,
        relative_path: str | None = None,
        *,
        _chain: frozenset[str] = frozenset(),
        observer: ObservabilityWatcher | None = None,
    ) -> Scene:
        """Load typed protobuf or legacy JSON into the shared Scene/Level model."""
        path = self.document_file(relative_path)
        value = relative_path or self.entrypoint
        expected_kind = self._registered_document_kind(value)
        try:
            with _observe_stage(observer, "document:load"):
                with _observe_stage(observer, "document:read"):
                    payload = path.read_bytes()
                if str(path).casefold().endswith(".pb"):
                    with _observe_stage(observer, "document:decode"):
                        envelope = parse_protobuf(payload)
                    with _observe_stage(observer, "document:convert"):
                        data = protobuf_to_document_data(envelope)
                        _apply_expected_document_kind(data, expected_kind)
                else:
                    with _observe_stage(observer, "document:decode"):
                        data = decode_json_payload(payload)
                        _apply_expected_document_kind(data, expected_kind)
                with _observe_stage(observer, "document:construct"):
                    document = from_json(data)

                current_chain = _chain | ({value} if value is not None else set())
                with _observe_stage(observer, "scene:resolve_instances"):
                    resolve_scene_instances(
                        document,
                        resolve_source=lambda source: self.load_scene(
                            source, _chain=current_chain, observer=observer
                        ),
                        chain=current_chain,
                    )
        except (OSError, DocumentCodecError) as exc:
            raise ProjectError(str(exc)) from exc
        self.set_active_scene(document)
        return document

    def load_scene(
        self,
        relative_path: str | None = None,
        *,
        _chain: frozenset[str] = frozenset(),
        observer: ObservabilityWatcher | None = None,
    ) -> Scene:
        # Compatibility API: Level is a Scene subtype and can still be loaded
        # by older runtime callers. SceneInstance resolution separately rejects
        # Level sources before materialization.
        return self.load_document(relative_path, _chain=_chain, observer=observer)

    def save_scene(self, scene: Scene, relative_path: str | None = None) -> Path:
        """Write a legacy JSON Scene for compatibility/import tooling.

        New editor documents use ``save_document`` and typed ``.scene.pb``
        paths. This method intentionally remains the explicit legacy writer.
        """
        if isinstance(scene, Level):
            raise ProjectError("save_scene cannot save a Level; use save_document")
        path = self.scene_file(relative_path)
        if str(path).casefold().endswith(".scene.pb"):
            return self.save_document(scene, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(scene.to_dict(include_instance_content=False), indent=2))
        value = relative_path or self.start_scene
        if value is not None:
            self.register_scene_path(value)
        return path

    def save_document(self, document: Scene, relative_path: str | None = None) -> Path:
        """Save one canonical typed protobuf document, never a JSON sidecar."""
        path = self.document_file(relative_path)
        expected_kind = kind_for_document_path(path)
        actual_kind = document.document_kind
        if expected_kind is None:
            raise ProjectError(
                "legacy JSON documents are read-only through save_document; "
                "migrate the project or Save As to a typed .scene.pb/.level.pb path"
            )
        if expected_kind != actual_kind:
            raise ProjectError(
                f"document extension declares {expected_kind.value}, but document is "
                f"{actual_kind.value}"
            )
        if expected_kind is DocumentKind.SCENE and not str(path).endswith(".scene.pb"):
            raise ProjectError("Scene documents must use the .scene.pb extension")
        if expected_kind is DocumentKind.LEVEL and not str(path).endswith(".level.pb"):
            raise ProjectError("Level documents must use the .level.pb extension")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_bytes(
                path,
                encode_protobuf(document.to_dict(include_instance_content=False)),
            )
        except DocumentCodecError as exc:
            raise ProjectError(str(exc)) from exc
        value = relative_path or self.entrypoint
        if value is not None:
            if isinstance(document, Level):
                self.register_level_path(value)
            else:
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
        if self._entrypoint is not None:
            data["entrypoint"] = self._entrypoint
        if self._level_paths:
            data["levels"] = list(self._level_paths)
        if self.input_settings:
            data["input"] = dict(self.input_settings)
        if self.script_entry_point != "__main__.py":
            data["script_entry_point"] = self.script_entry_point
        return data

    def save(self) -> None:
        """Write project.json to disk. Creates directories if needed."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(exist_ok=True)
        self.levels_dir.mkdir(exist_ok=True)
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
        legacy_start_scene = data.get("start_scene")
        canonical_entrypoint = data.get("entrypoint")
        if legacy_start_scene is not None and not isinstance(legacy_start_scene, str):
            raise ProjectError("project start_scene must be a string")
        if canonical_entrypoint is not None and not isinstance(canonical_entrypoint, str):
            raise ProjectError("project entrypoint must be a string")
        if (
            canonical_entrypoint is not None
            and legacy_start_scene is not None
            and canonical_entrypoint != legacy_start_scene
        ):
            raise ProjectError("entrypoint conflicts with legacy start_scene")
        start_scene = canonical_entrypoint or legacy_start_scene
        if start_scene is not None:
            cls._validate_entrypoint(start_scene)
        input_settings = data.get("input", {})
        if not isinstance(input_settings, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in input_settings.items()
        ):
            raise ProjectError("project input settings must be a string mapping")
        if any(
            ":" not in value or not all(value.split(":", 1)) for value in input_settings.values()
        ):
            raise ProjectError("project input bindings must look like keyboard:left")
        legacy_entry_point = data.get("entry_point")
        script_entry_point_value = data.get("script_entry_point")
        if (
            legacy_entry_point is not None
            and script_entry_point_value is not None
            and legacy_entry_point != script_entry_point_value
        ):
            raise ProjectError("script_entry_point conflicts with legacy entry_point")
        entry_point = script_entry_point_value or legacy_entry_point or "__main__.py"
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
            entrypoint=start_scene,
            script_entry_point=entry_point,
        )
        for scene_path in scenes:
            if not isinstance(scene_path, str):
                raise ProjectError("project scene paths must be strings")
            project._validate_scene_path(scene_path)
            project.register_scene_path(scene_path)
        levels = data.get("levels", [])
        if not isinstance(levels, list) or not all(isinstance(value, str) for value in levels):
            raise ProjectError("project level paths must be strings")
        for level_path in levels:
            project.register_level_path(level_path)
        if project.start_scene is not None:
            project._validate_entrypoint(project.start_scene)
            if (
                project.entrypoint in project.level_paths()
                and project.entrypoint in project.scene_paths()
            ):
                raise ProjectError("project entrypoint is registered as both a Scene and Level")
        if project.start_scene is None and project.scene_paths():
            project._entrypoint = project.scene_paths()[0]
        for directory in (
            project.scenes_dir,
            project.levels_dir,
            project.assets_dir,
            project.scripts_dir,
        ):
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
                entrypoint="scenes/main.scene.pb",
            )
            project.register_scene_path("scenes/main.scene.pb")
            project.save()
            project.save_document(Scene("Main"), "scenes/main.scene.pb")
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
        try:
            kind = kind_for_document_path(relative_path)
        except DocumentCodecError as exc:
            raise ProjectError(str(exc)) from exc
        if kind is DocumentKind.LEVEL:
            raise ProjectError(f"Scene registry path has a Level extension: {relative_path!r}")

    @staticmethod
    def _validate_level_path(relative_path: str) -> None:
        Project._validate_entrypoint(relative_path)
        kind = kind_for_document_path(relative_path)
        if kind is DocumentKind.SCENE:
            raise ProjectError(f"Level registry path has a Scene extension: {relative_path!r}")

    @staticmethod
    def _validate_entrypoint(relative_path: str) -> None:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts or not relative_path.strip():
            raise ProjectError(f"entrypoint must be project-relative: {relative_path!r}")
        try:
            kind_for_document_path(relative_path)
        except DocumentCodecError as exc:
            raise ProjectError(str(exc)) from exc

    def _registered_document_kind(self, relative_path: str | None) -> DocumentKind | None:
        if relative_path is None:
            return None
        extension_kind = kind_for_document_path(relative_path)
        if extension_kind is not None:
            if relative_path in self._level_paths and extension_kind is not DocumentKind.LEVEL:
                raise ProjectError(
                    f"Level registry conflicts with document extension: {relative_path}"
                )
            if relative_path in self._scene_paths and extension_kind is not DocumentKind.SCENE:
                raise ProjectError(
                    f"Scene registry conflicts with document extension: {relative_path}"
                )
        elif relative_path in self._level_paths:
            return DocumentKind.LEVEL
        return extension_kind

    def migrate_to_protobuf(self) -> dict[str, str]:
        """Explicitly migrate registered legacy JSON documents to typed PB.

        Legacy files are retained as import/recovery inputs. The manifest and
        parsed Scene Instance source references are switched to the PB targets
        only after every document has decoded successfully.
        """
        paths = list(dict.fromkeys((*self._scene_paths, *self._level_paths)))
        if self.entrypoint is not None and self.entrypoint not in paths:
            paths.append(self.entrypoint)
        legacy_paths = [path for path in paths if str(path).casefold().endswith(".json")]
        mapping: dict[str, str] = {}
        documents: dict[str, Scene] = {}
        for source in legacy_paths:
            document = self.load_document(source)
            documents[source] = document
            if isinstance(document, Level):
                target = f"levels/{Path(source).stem}.level.pb"
            else:
                target = f"scenes/{Path(source).stem}.scene.pb"
            mapping[source] = target

        for document in documents.values():
            self._rewrite_scene_instance_sources(document, mapping)
        for source, document in documents.items():
            self.save_document(document, mapping[source])

        self._scene_paths = list(
            dict.fromkeys(mapping.get(path, path) for path in self._scene_paths)
        )
        self._level_paths = list(
            dict.fromkeys(mapping.get(path, path) for path in self._level_paths)
        )
        if self.entrypoint is not None:
            self._entrypoint = mapping.get(self.entrypoint, self.entrypoint)
        self.schema_version = CURRENT_SCHEMA_VERSION
        self.save()
        return mapping

    @staticmethod
    def _rewrite_scene_instance_sources(scene: Scene, mapping: dict[str, str]) -> None:
        for entity in scene.entities:
            component = entity.get_component(SceneInstanceComponent)
            if component is not None:
                component.source_path = mapping.get(component.source_path, component.source_path)

    def __repr__(self) -> str:
        return f"Project({self.name!r}, path={self.path})"
