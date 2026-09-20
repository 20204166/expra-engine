"""Read-only and writable directory and ZIP resource mounts."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from .errors import (
    MalformedPackageManifestError,
    ResourceNotFoundError,
    ResourcePermissionError,
    UnsafeArchiveMemberError,
)
from .ids import ResourceId
from .packages import PackageManifest


@dataclass(frozen=True, slots=True)
class MountSpec:
    """Logical scope and resolution policy for a mount."""

    name: str
    scheme: str
    namespace: str | None = None
    prefix: str = ""
    precedence: int = 0
    read_only: bool = True

    def matches(self, resource_id: ResourceId) -> bool:
        if resource_id.scheme != self.scheme or resource_id.namespace != self.namespace:
            return False
        return (
            not self.prefix
            or resource_id.path == self.prefix
            or resource_id.path.startswith(f"{self.prefix}/")
        )

    def relative_path(self, resource_id: ResourceId) -> str:
        if not self.matches(resource_id):
            raise ResourceNotFoundError(
                operation="resolve", logical_id=resource_id, mount=self.name
            )
        if not self.prefix:
            return resource_id.path
        return resource_id.path[len(self.prefix) + 1 :]


class ResourceMount(Protocol):
    spec: MountSpec

    def locate(self, resource_id: ResourceId) -> ResourceLocation | None:
        """Return a resource location, or ``None`` when it is not provided."""

    def read_bytes(self, resource_id: ResourceId) -> bytes: ...

    def open(self, resource_id: ResourceId) -> IO[bytes]: ...

    def write_bytes(self, resource_id: ResourceId, data: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class DirectoryLocation:
    path: Path
    size: int
    modified_ns: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ArchiveLocation:
    member: str
    size: int
    modified_ns: int | None
    content_hash: str
    physical_path: Path | None = None


ResourceLocation = DirectoryLocation | ArchiveLocation


class DirectoryMount:
    """Expose files below a root while rejecting symlink escapes."""

    def __init__(self, root: Path, spec: MountSpec) -> None:
        self.root = Path(root).resolve()
        self.spec = spec

    def _confined_path(self, resource_id: ResourceId) -> Path | None:
        if not self.spec.matches(resource_id):
            return None
        candidate = (self.root / self.spec.relative_path(resource_id)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate

    def locate(self, resource_id: ResourceId) -> DirectoryLocation | None:
        candidate = self._confined_path(resource_id)
        if candidate is None or not candidate.is_file():
            return None
        try:
            data = candidate.read_bytes()
            stat = candidate.stat()
        except OSError:
            return None
        return DirectoryLocation(
            path=candidate,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            content_hash=hashlib.sha256(data).hexdigest(),
        )

    def read_bytes(self, resource_id: ResourceId) -> bytes:
        location = self.locate(resource_id)
        if location is None:
            raise ResourceNotFoundError(
                operation="read", logical_id=resource_id, mount=self.spec.name
            )
        return location.path.read_bytes()

    def open(self, resource_id: ResourceId) -> IO[bytes]:
        location = self.locate(resource_id)
        if location is None:
            raise ResourceNotFoundError(
                operation="open", logical_id=resource_id, mount=self.spec.name
            )
        return location.path.open("rb")

    def write_bytes(self, resource_id: ResourceId, data: bytes) -> None:
        if self.spec.read_only:
            raise ResourcePermissionError(
                "Mount is read-only",
                operation="write",
                logical_id=resource_id,
                mount=self.spec.name,
            )
        candidate = self._confined_path(resource_id)
        if candidate is None:
            raise ResourcePermissionError(
                "Resource is outside mount",
                operation="write",
                logical_id=resource_id,
                mount=self.spec.name,
            )
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate = candidate.resolve()
            candidate.relative_to(self.root)
            candidate.write_bytes(data)
        except (OSError, ValueError) as exc:
            raise ResourcePermissionError(
                "Resource cannot be written",
                operation="write",
                logical_id=resource_id,
                mount=self.spec.name,
            ) from exc


class ArchiveMount:
    """Expose validated ZIP members through the same contract as directories."""

    def __init__(self, archive: Path, spec: MountSpec) -> None:
        self.archive = Path(archive)
        self.spec = spec
        try:
            self._zip = zipfile.ZipFile(self.archive)
        except (OSError, zipfile.BadZipFile) as exc:
            raise MalformedPackageManifestError(
                "Archive cannot be opened", operation="mount", mount=spec.name
            ) from exc
        self._infos: dict[str, zipfile.ZipInfo] = {}
        try:
            self._index_members()
            self.manifest = self._load_manifest()
            self._validate_manifest()
        except Exception:
            self._zip.close()
            raise

    def _index_members(self) -> None:
        for info in self._zip.infolist():
            name = info.filename
            if not name or name.endswith("/"):
                continue
            if "\\" in name or name.startswith("/") or name.startswith("\\"):
                raise UnsafeArchiveMemberError(
                    "Archive member uses an unsafe path", operation="mount", mount=self.spec.name
                )
            parts = name.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise UnsafeArchiveMemberError(
                    "Archive member uses an unsafe path", operation="mount", mount=self.spec.name
                )
            if len(parts[0]) == 2 and parts[0][1] == ":":
                raise UnsafeArchiveMemberError(
                    "Archive member uses a drive path", operation="mount", mount=self.spec.name
                )
            if name in self._infos:
                raise UnsafeArchiveMemberError(
                    "Archive contains duplicate members", operation="mount", mount=self.spec.name
                )
            self._infos[name] = info

    def _load_manifest(self) -> PackageManifest | None:
        if "package.json" not in self._infos:
            if self.spec.scheme == "package":
                raise MalformedPackageManifestError(
                    "Package archive is missing package.json",
                    operation="mount",
                    mount=self.spec.name,
                )
            return None
        try:
            import json

            raw = json.loads(self._zip.read("package.json"))
            return PackageManifest.from_mapping(raw)
        except MalformedPackageManifestError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise MalformedPackageManifestError(
                "Package manifest is not valid JSON", operation="mount", mount=self.spec.name
            ) from exc

    def _validate_manifest(self) -> None:
        if self.manifest is None:
            return
        if self.spec.namespace != self.manifest.identity:
            raise MalformedPackageManifestError(
                "Package identity does not match mount namespace",
                operation="mount",
                mount=self.spec.name,
                package=self.manifest.identity,
            )
        declared = {resource.path: resource for resource in self.manifest.resources}
        actual = set(self._infos) - {"package.json"}
        if actual != set(declared):
            raise MalformedPackageManifestError(
                "Manifest resources do not match archive members",
                operation="mount",
                mount=self.spec.name,
                package=self.manifest.identity,
            )
        for path, resource in declared.items():
            data = self._zip.read(path)
            if len(data) != resource.size or hashlib.sha256(data).hexdigest() != resource.sha256:
                raise MalformedPackageManifestError(
                    "Manifest resource metadata does not match archive content",
                    operation="mount",
                    mount=self.spec.name,
                    package=self.manifest.identity,
                )

    def _member_name(self, resource_id: ResourceId) -> str | None:
        if not self.spec.matches(resource_id):
            return None
        name = self.spec.relative_path(resource_id)
        return name if name in self._infos else None

    def locate(self, resource_id: ResourceId) -> ArchiveLocation | None:
        name = self._member_name(resource_id)
        if name is None:
            return None
        info = self._infos[name]
        data = self._zip.read(name)
        return ArchiveLocation(
            member=name,
            size=info.file_size,
            modified_ns=_zip_modified_ns(info),
            content_hash=hashlib.sha256(data).hexdigest(),
        )

    def read_bytes(self, resource_id: ResourceId) -> bytes:
        name = self._member_name(resource_id)
        if name is None:
            raise ResourceNotFoundError(
                operation="read", logical_id=resource_id, mount=self.spec.name
            )
        return self._zip.read(name)

    def open(self, resource_id: ResourceId) -> IO[bytes]:
        name = self._member_name(resource_id)
        if name is None:
            raise ResourceNotFoundError(
                operation="open", logical_id=resource_id, mount=self.spec.name
            )
        return self._zip.open(name, "r")

    def write_bytes(self, resource_id: ResourceId, data: bytes) -> None:
        del data
        raise ResourcePermissionError(
            "Archive mounts are read-only",
            operation="write",
            logical_id=resource_id,
            mount=self.spec.name,
        )

    def extract(self, resource_id: ResourceId, cache_dir: Path) -> Path:
        from .packages import extract_archive_resource

        return extract_archive_resource(self, resource_id, cache_dir)

    def close(self) -> None:
        self._zip.close()


def _zip_modified_ns(info: zipfile.ZipInfo) -> int | None:
    try:
        import datetime

        timestamp = datetime.datetime(*info.date_time, tzinfo=datetime.UTC).timestamp()
        return int(timestamp * 1_000_000_000)
    except (OverflowError, ValueError):
        return None
