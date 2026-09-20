"""Package manifests and explicit, confined archive extraction."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import MalformedPackageManifestError, ResourceNotFoundError, UnsafeArchiveMemberError

if TYPE_CHECKING:
    from .ids import ResourceId
    from .mounts import ArchiveMount


@dataclass(frozen=True, slots=True)
class PackageResource:
    path: str
    size: int
    sha256: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageManifest:
    identity: str
    version: str
    format_version: int
    resources: tuple[PackageResource, ...]
    dependencies: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> PackageManifest:
        if not isinstance(value, Mapping):
            raise MalformedPackageManifestError("Package manifest must be an object")
        identity = value.get("identity")
        version = value.get("version")
        format_version = value.get("format_version")
        raw_resources = value.get("resources")
        raw_dependencies = value.get("dependencies", [])
        if (
            not isinstance(identity, str)
            or not identity
            or not isinstance(version, str)
            or not version
            or not isinstance(format_version, int)
            or format_version < 1
            or not isinstance(raw_resources, list)
            or not raw_resources
            or not isinstance(raw_dependencies, list)
            or any(not isinstance(item, str) for item in raw_dependencies)
        ):
            raise MalformedPackageManifestError("Package manifest has invalid top-level fields")
        resources: list[PackageResource] = []
        paths: set[str] = set()
        for raw in raw_resources:
            if not isinstance(raw, Mapping):
                raise MalformedPackageManifestError("Package resource must be an object")
            path = raw.get("path")
            size = raw.get("size")
            sha256 = raw.get("sha256")
            dependencies = raw.get("dependencies", [])
            if (
                not isinstance(path, str)
                or not path
                or path in paths
                or not isinstance(size, int)
                or size < 0
                or not isinstance(sha256, str)
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256)
                or not isinstance(dependencies, list)
                or any(not isinstance(item, str) for item in dependencies)
            ):
                raise MalformedPackageManifestError("Package resource metadata is invalid")
            if (
                "\\" in path
                or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise MalformedPackageManifestError("Package resource path is unsafe")
            paths.add(path)
            resources.append(PackageResource(path, size, sha256, tuple(dependencies)))
        return cls(identity, version, format_version, tuple(resources), tuple(raw_dependencies))


def extract_archive_resource(mount: ArchiveMount, resource_id: ResourceId, cache_dir: Path) -> Path:
    """Extract one archive member into a hash-keyed cache using atomic replacement."""
    location = mount.locate(resource_id)
    if location is None:
        raise ResourceNotFoundError(
            operation="extract", logical_id=resource_id, mount=mount.spec.name
        )
    data = mount.read_bytes(resource_id)
    digest = hashlib.sha256(data).hexdigest()
    relative = Path(location.member)
    if relative.is_absolute() or ".." in relative.parts or "\\" in location.member:
        raise UnsafeArchiveMemberError(
            "Extraction target is unsafe", operation="extract", mount=mount.spec.name
        )
    target_root = (
        Path(cache_dir).resolve()
        / (mount.manifest.identity if mount.manifest else mount.spec.name)
        / digest
    )
    target = target_root / relative
    target_root.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.resolve().relative_to(target_root.resolve())
    except ValueError as exc:
        raise UnsafeArchiveMemberError(
            "Extraction target escapes cache directory",
            operation="extract",
            mount=mount.spec.name,
        ) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            target.resolve().relative_to(target_root.resolve())
        except ValueError as exc:
            raise UnsafeArchiveMemberError(
                "Extraction target escapes cache directory",
                operation="extract",
                mount=mount.spec.name,
            ) from exc
        return target
    fd, temporary_name = tempfile.mkstemp(prefix=".extract-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
    return target
