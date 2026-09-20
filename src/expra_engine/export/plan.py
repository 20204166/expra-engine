"""ExportPlan — immutable, fully validated export configuration.

Separation from _release.py is intentional: _release.py builds the Expra
engine wheel; ExportPlan describes packaging a GAME MADE WITH Expra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from expra_engine.filesystem import ResourceId, ResourceService


class ExportTarget(StrEnum):
    WINDOWS = "windows"
    LINUX = "linux"


class PythonArch(StrEnum):
    AMD64 = "amd64"
    ARM64 = "arm64"


class RuntimeProfile(StrEnum):
    """Explicit runtime dependency and engine-module selection."""

    NONE = "none"
    PYGAME = "pygame"


_GAME_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+")
_PY_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class ExportPlan:
    """Immutable, validated description of a single game export operation."""

    project_dir: Path
    entry_point: str  # path relative to project_dir, e.g. "mygame/__main__.py"
    output_dir: Path
    target: ExportTarget
    game_name: str
    game_version: str
    python_version: str  # major.minor.patch, e.g. "3.12.4"
    arch: PythonArch = PythonArch.AMD64
    compile_bytecode: bool = True
    exclude_patterns: frozenset[str] = field(default_factory=frozenset)
    extra_packages: tuple[str, ...] = ()
    debug_launcher: bool = True
    resource_service: ResourceService | None = None
    resource_ids: tuple[ResourceId | str, ...] = ()
    runtime_profile: RuntimeProfile = RuntimeProfile.NONE

    def __post_init__(self) -> None:
        if not self.project_dir.is_dir():
            raise ValueError(f"project_dir does not exist: {self.project_dir}")
        entry = self.project_dir / self.entry_point
        if not entry.exists():
            raise ValueError(f"entry_point not found: {entry}")
        if not _GAME_NAME_RE.match(self.game_name):
            raise ValueError(
                f"Invalid game_name {self.game_name!r}. "
                "Must start with alphanumeric and contain only A-Z, a-z, 0-9, space, _, -"
            )
        if not _SEMVER_RE.match(self.game_version):
            raise ValueError(
                f"Invalid game_version {self.game_version!r}. Must start with major.minor"
            )
        if not _PY_VERSION_RE.match(self.python_version):
            raise ValueError(
                f"Invalid python_version {self.python_version!r}. Must be major.minor.patch"
            )
        if not self.output_dir.is_absolute():
            raise ValueError(f"output_dir must be absolute: {self.output_dir}")
        object.__setattr__(
            self,
            "resource_ids",
            tuple(
                item if isinstance(item, ResourceId) else ResourceId.parse(item)
                for item in self.resource_ids
            ),
        )
