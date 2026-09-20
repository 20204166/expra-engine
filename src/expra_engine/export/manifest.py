"""Asset manifest, build manifest, and runtime boundary enforcement.

EXCLUDED_DEV_PACKAGES lists packages that must NOT be present in exported games.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from expra_engine.filesystem import ResourceId

if TYPE_CHECKING:
    from expra_engine.filesystem import ResourceService

EXCLUDED_DEV_PACKAGES: frozenset[str] = frozenset(
    {
        "expra_engine.editor",
        "expra_engine.ui",
        "tkinter",
        "ttkbootstrap",
    }
)

ASSET_IGNORE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".psd",
        ".blend",
        ".blend1",
        ".kra",
        ".kra~",
        ".gitignore",
    }
)

ASSET_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "builds",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)

ASSET_IGNORE_CODE_SUFFIXES: frozenset[str] = frozenset({".py"})


@dataclass(frozen=True)
class AssetEntry:
    path: str  # relative to project root, POSIX separators
    size: int
    sha256: str
    logical_id: str | None = None
    source: str | None = None
    destination: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def provenance(self) -> str | None:
        return self.source


@dataclass
class AssetManifest:
    entries: list[AssetEntry] = field(default_factory=list)

    @classmethod
    def collect(
        cls,
        source_dir: Path,
        *,
        extra_exclude_patterns: frozenset[str] = frozenset(),
        include_source: bool = True,
        resource_service: ResourceService | None = None,
        logical_ids: Iterable[ResourceId | str] = (),
    ) -> AssetManifest:
        """Collect legacy project files or explicitly resolved logical resources."""
        requested = tuple(_as_resource_id(item) for item in logical_ids)
        if resource_service is not None and requested:
            return cls._collect_resources(resource_service, requested)
        entries: list[AssetEntry] = []
        for file in _walk(source_dir):
            rel = file.relative_to(source_dir)
            if _should_exclude(rel, extra_exclude_patterns, include_source=include_source):
                continue
            sha256 = _hash_file(file)
            relative = rel.as_posix()
            logical_id = str(ResourceId.from_project_path(relative)) if resource_service else None
            entries.append(
                AssetEntry(
                    path=relative,
                    size=file.stat().st_size,
                    sha256=sha256,
                    logical_id=logical_id,
                    source="project-assets" if resource_service else None,
                    destination=relative,
                    aliases=(logical_id,) if logical_id else (),
                )
            )
        entries.sort(key=lambda e: e.path)
        return cls(entries=entries)

    @classmethod
    def _collect_resources(
        cls, service: ResourceService, requested: tuple[ResourceId, ...]
    ) -> AssetManifest:
        all_ids = set(requested)
        for logical_id in requested:
            all_ids.update(service.dependencies.transitive_dependencies(logical_id))

        by_hash: dict[str, AssetEntry] = {}
        for logical_id in sorted(all_ids, key=str):
            handle = service.resolver.resolve(logical_id)
            data = service.read_bytes(logical_id)
            destination = _resource_destination(logical_id)
            entry = AssetEntry(
                path=destination,
                size=handle.metadata.size,
                sha256=handle.metadata.content_hash,
                logical_id=str(logical_id),
                source=handle.mount,
                destination=destination,
                aliases=(str(logical_id),),
            )
            if len(data) != entry.size:
                raise ValueError(f"Resource size changed while exporting {logical_id}")
            existing = by_hash.get(entry.sha256)
            if existing is None:
                by_hash[entry.sha256] = entry
            else:
                by_hash[entry.sha256] = AssetEntry(
                    path=existing.path,
                    size=existing.size,
                    sha256=existing.sha256,
                    logical_id=existing.logical_id,
                    source=existing.source,
                    destination=existing.destination,
                    aliases=tuple(sorted((*existing.aliases, str(logical_id)))),
                )
        return cls(entries=sorted(by_hash.values(), key=lambda item: item.path))

    def to_json(self) -> str:
        return json.dumps({"entries": [asdict(e) for e in self.entries]}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> AssetManifest:
        data = json.loads(text)
        entries = []
        for raw in data["entries"]:
            if "source" not in raw and "provenance" in raw:
                raw["source"] = raw.pop("provenance")
            raw["aliases"] = tuple(raw.get("aliases", ()))
            entries.append(AssetEntry(**raw))
        return cls(entries=entries)


@dataclass(frozen=True)
class BuildManifest:
    """Written to build_manifest.json in the exported game root."""

    game_name: str
    game_version: str
    engine_version: str
    target: str
    python_version: str
    arch: str
    compile_bytecode: bool
    entry_point: str
    build_timestamp: str  # ISO 8601 UTC
    runtime_profile: str = "none"

    def to_json(self) -> str:
        return json.dumps(
            {
                "game_name": self.game_name,
                "game_version": self.game_version,
                "engine_version": self.engine_version,
                "target": self.target,
                "python_version": self.python_version,
                "arch": self.arch,
                "compile_bytecode": self.compile_bytecode,
                "entry_point": self.entry_point,
                "build_timestamp": self.build_timestamp,
                "runtime_profile": self.runtime_profile,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> BuildManifest:
        return cls(**json.loads(text))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk(root: Path) -> Iterator[Path]:
    resolved_root = root.resolve()
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        try:
            child.resolve().relative_to(resolved_root)
        except ValueError:
            # Do not package a project symlink that escapes its root.
            continue
        if child.is_file():
            yield child


def _should_exclude(
    rel: Path,
    extra: frozenset[str],
    *,
    include_source: bool,
) -> bool:
    if any(part in ASSET_IGNORE_DIRS for part in rel.parts):
        return True
    if rel.suffix in ASSET_IGNORE_SUFFIXES:
        return True
    if not include_source and rel.suffix in ASSET_IGNORE_CODE_SUFFIXES:
        return True
    return rel.as_posix() in extra


def _hash_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def _as_resource_id(value: ResourceId | str) -> ResourceId:
    return value if isinstance(value, ResourceId) else ResourceId.parse(value)


def _resource_destination(resource_id: ResourceId) -> str:
    if resource_id.namespace is None:
        return f"resources/{resource_id.scheme}/{resource_id.path}"
    return f"resources/{resource_id.scheme}/{resource_id.namespace}/{resource_id.path}"
