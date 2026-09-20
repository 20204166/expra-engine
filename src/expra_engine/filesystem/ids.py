"""Renderer-neutral logical resource identities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from .errors import InvalidResourceIdError

_SCHEMES = frozenset({"assets", "engine", "package", "user"})
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")
_DRIVE_RE = re.compile(r"^[a-zA-Z]:([/\\]|$)")


@dataclass(frozen=True, slots=True)
class ResourceId:
    """A stable logical name for a resource, independent of its mount path."""

    scheme: str
    namespace: str | None
    path: str

    def __post_init__(self) -> None:
        if self.scheme not in _SCHEMES or not _SCHEME_RE.fullmatch(self.scheme):
            raise InvalidResourceIdError("construct", logical_id=self.scheme)
        if self.namespace is not None:
            _validate_component(self.namespace, "namespace", "construct", self)
        _validate_path(self.path, "construct", self)
        if self.scheme == "package" and self.namespace is None:
            raise InvalidResourceIdError(
                "Package resource IDs require a namespace", logical_id=self
            )

    @classmethod
    def parse(cls, value: str) -> ResourceId:
        """Parse a canonical logical ID without consulting the local filesystem."""
        if not isinstance(value, str) or not value:
            raise InvalidResourceIdError("parse", logical_id=value)
        if "\x00" in value or "://" not in value:
            raise InvalidResourceIdError("parse", logical_id=value)
        scheme, remainder = value.split("://", 1)
        if scheme != scheme.lower() or scheme not in _SCHEMES:
            raise InvalidResourceIdError("parse", logical_id=value)
        if "://" in remainder:
            raise InvalidResourceIdError("parse", logical_id=value)

        namespace = None
        path = remainder
        if scheme == "package":
            parts = remainder.split("/", 1)
            if len(parts) != 2:
                raise InvalidResourceIdError("parse", logical_id=value)
            namespace, path = parts
        resource_id = cls.__new__(cls)
        object.__setattr__(resource_id, "scheme", scheme)
        object.__setattr__(resource_id, "namespace", namespace)
        object.__setattr__(resource_id, "path", path)
        try:
            resource_id.__post_init__()
        except InvalidResourceIdError:
            raise InvalidResourceIdError("parse", logical_id=value) from None
        return resource_id

    @classmethod
    def from_project_path(cls, path: str | PathLike[str], *, scheme: str = "assets") -> ResourceId:
        """Create an assets ID from a project-relative path."""
        raw_path = str(path).replace("\\", "/")
        if Path(raw_path).is_absolute() or _DRIVE_RE.match(raw_path):
            raise InvalidResourceIdError("from_project_path", logical_id=raw_path)
        if scheme != "assets":
            raise InvalidResourceIdError("from_project_path", logical_id=raw_path)
        try:
            return cls(scheme, None, raw_path)
        except InvalidResourceIdError:
            raise InvalidResourceIdError("from_project_path", logical_id=raw_path) from None

    def __str__(self) -> str:
        prefix = f"{self.scheme}://"
        if self.namespace is not None:
            prefix += f"{self.namespace}/"
        return prefix + self.path


def _validate_component(
    component: str, label: str, operation: str, logical_id: ResourceId | str | None
) -> None:
    if not component or component in {".", ".."} or "/" in component or "\\" in component:
        raise InvalidResourceIdError(f"Invalid {label}", operation=operation, logical_id=logical_id)
    if "\x00" in component or ":" in component:
        raise InvalidResourceIdError(f"Invalid {label}", operation=operation, logical_id=logical_id)


def _validate_path(path: str, operation: str, logical_id: ResourceId | str | None) -> None:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise InvalidResourceIdError(
            "Invalid resource path", operation=operation, logical_id=logical_id
        )
    if "\\" in path or path.startswith("/") or _DRIVE_RE.match(path):
        raise InvalidResourceIdError(
            "Invalid resource path", operation=operation, logical_id=logical_id
        )
    components = path.split("/")
    if any(not component or component in {".", ".."} for component in components):
        raise InvalidResourceIdError(
            "Invalid resource path", operation=operation, logical_id=logical_id
        )
