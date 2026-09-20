"""Typed, renderer-neutral errors for resource operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ids import ResourceId


class FilesystemError(Exception):
    """Base error with safe logical operation context."""

    def __init__(
        self,
        message: str = "Filesystem operation failed",
        *,
        operation: str | None = None,
        logical_id: ResourceId | str | None = None,
        mount: str | None = None,
        package: str | None = None,
        path: Any = None,
    ) -> None:
        del path  # Physical paths must not become part of the public diagnostic.
        self.operation = operation
        self.logical_id = logical_id
        self.mount = mount
        self.package = package
        context = [message]
        if operation:
            context.append(f"operation={operation}")
        if logical_id is not None:
            context.append(f"resource={logical_id}")
        if mount:
            context.append(f"mount={mount}")
        if package:
            context.append(f"package={package}")
        super().__init__(": ".join(context))


class InvalidResourceIdError(FilesystemError, ValueError):
    """A logical resource ID is malformed or unsafe."""


class MountNotFoundError(FilesystemError):
    """A requested mount is not registered."""


class ResourceNotFoundError(FilesystemError, FileNotFoundError):
    """A logical resource cannot be resolved."""


class DuplicateResourceError(FilesystemError):
    """Two mounts provide an ambiguous resource."""


class ResourcePermissionError(FilesystemError, PermissionError):
    """The requested resource operation is not permitted."""


class UnsafeArchiveMemberError(FilesystemError):
    """An archive member or extraction target is unsafe."""


class MalformedPackageManifestError(FilesystemError):
    """A package manifest is malformed or inconsistent."""


class DependencyError(FilesystemError):
    """Base error for dependency resolution failures."""


class DependencyCycleError(DependencyError):
    """A resource dependency graph contains a cycle."""


class MissingDependencyError(DependencyError):
    """A declared resource dependency cannot be resolved."""


class DecodeError(FilesystemError):
    """A renderer-independent adapter failed to decode a resource."""


class ResourceCancelledError(FilesystemError):
    """A resource operation was cancelled."""


class StaleResourceError(FilesystemError):
    """A resource result belongs to an obsolete operation generation."""
