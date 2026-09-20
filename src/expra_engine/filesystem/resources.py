"""Logical resource handles and deterministic mount resolution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .errors import DuplicateResourceError, ResourceNotFoundError
from .ids import ResourceId
from .mounts import ResourceLocation, ResourceMount


@dataclass(frozen=True, slots=True)
class ResourceMetadata:
    size: int
    modified_ns: int | None
    content_hash: str
    physical_path: Path | None


@dataclass(frozen=True, slots=True)
class ResourceHandle:
    logical_id: ResourceId
    mount: str
    metadata: ResourceMetadata
    _mount_impl: ResourceMount

    @property
    def physical_path(self) -> Path | None:
        return self.metadata.physical_path

    def read_bytes(self) -> bytes:
        return self._mount_impl.read_bytes(self.logical_id)

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self.read_bytes().decode(encoding, errors)

    def open(self) -> IO[bytes]:
        return self._mount_impl.open(self.logical_id)


class ResourceResolver:
    """Resolve logical IDs using explicit precedence and conflict detection."""

    def __init__(self, mounts: Iterable[ResourceMount] = ()) -> None:
        self._mounts: dict[str, ResourceMount] = {}
        for mount in mounts:
            self.mount(mount)

    def mount(self, mount: ResourceMount) -> None:
        self._mounts[mount.spec.name] = mount

    def mount_for(self, name: str) -> ResourceMount | None:
        return self._mounts.get(name)

    def unmount(self, name: str) -> None:
        self._mounts.pop(name, None)

    def _candidates(self, resource_id: ResourceId) -> list[tuple[ResourceMount, ResourceLocation]]:
        candidates: list[tuple[ResourceMount, ResourceLocation]] = []
        for mount in self._mounts.values():
            if not mount.spec.matches(resource_id):
                continue
            location = mount.locate(resource_id)
            if location is not None:
                candidates.append((mount, location))
        return candidates

    def resolve(self, resource_id: ResourceId) -> ResourceHandle:
        candidates = self._candidates(resource_id)
        if not candidates:
            raise ResourceNotFoundError(operation="resolve", logical_id=resource_id)
        highest = max(mount.spec.precedence for mount, _ in candidates)
        winners = [
            (mount, location) for mount, location in candidates if mount.spec.precedence == highest
        ]
        if len(winners) > 1:
            raise DuplicateResourceError(operation="resolve", logical_id=resource_id)
        mount, location = winners[0]
        return ResourceHandle(
            logical_id=resource_id,
            mount=mount.spec.name,
            metadata=ResourceMetadata(
                size=location.size,
                modified_ns=location.modified_ns,
                content_hash=location.content_hash,
                physical_path=getattr(location, "physical_path", getattr(location, "path", None)),
            ),
            _mount_impl=mount,
        )

    def write(self, resource_id: ResourceId, data: bytes) -> None:
        matching = [mount for mount in self._mounts.values() if mount.spec.matches(resource_id)]
        if not matching:
            raise ResourceNotFoundError(operation="write", logical_id=resource_id)
        highest = max(mount.spec.precedence for mount in matching)
        winners = [mount for mount in matching if mount.spec.precedence == highest]
        if len(winners) > 1:
            raise DuplicateResourceError(operation="write", logical_id=resource_id)
        mount = winners[0]
        mount.write_bytes(resource_id, data)
