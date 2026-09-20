"""Asset manifest, build manifest, and runtime boundary enforcement.

EXCLUDED_DEV_PACKAGES lists packages that must NOT be present in exported games.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

EXCLUDED_DEV_PACKAGES: frozenset[str] = frozenset({
    "expra_engine.editor",
    "expra_engine.ui",
    "tkinter",
    "ttkbootstrap",
})

ASSET_IGNORE_SUFFIXES: frozenset[str] = frozenset({
    ".psd", ".blend", ".blend1", ".kra", ".kra~", ".gitignore",
})

ASSET_IGNORE_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", ".venv", "venv", "builds", "dist",
    "build", ".mypy_cache", ".ruff_cache", ".pytest_cache",
})

ASSET_IGNORE_CODE_SUFFIXES: frozenset[str] = frozenset({".py"})


@dataclass(frozen=True)
class AssetEntry:
    path: str    # relative to project root, POSIX separators
    size: int
    sha256: str


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
    ) -> AssetManifest:
        """Walk source_dir and record every non-ignored file."""
        entries: list[AssetEntry] = []
        for file in _walk(source_dir):
            rel = file.relative_to(source_dir)
            if _should_exclude(rel, extra_exclude_patterns, include_source=include_source):
                continue
            sha256 = _hash_file(file)
            entries.append(
                AssetEntry(path=rel.as_posix(), size=file.stat().st_size, sha256=sha256)
            )
        entries.sort(key=lambda e: e.path)
        return cls(entries=entries)

    def to_json(self) -> str:
        return json.dumps({"entries": [asdict(e) for e in self.entries]}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> AssetManifest:
        data = json.loads(text)
        return cls(entries=[AssetEntry(**e) for e in data["entries"]])


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
    for child in sorted(root.rglob("*")):
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
