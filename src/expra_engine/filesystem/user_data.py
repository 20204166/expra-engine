"""Confined, writable storage that is separate from resource mounts."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from expra_engine.editor.persistence import atomic_write_text, fsync_directory

from .errors import FilesystemError

UserDataNamespace = Literal["application", "game"]
_DRIVE_RE = re.compile(r"^[a-zA-Z]:([/\\]|$)")


class UserDataError(FilesystemError):
    """A user-data operation failed without exposing its physical root."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        namespace: UserDataNamespace,
        relative_path: str,
    ) -> None:
        self.namespace = namespace
        self.relative_path = _safe_diagnostic_path(relative_path)
        super().__init__(
            message,
            operation=operation,
            logical_id=f"user://{namespace}/{self.relative_path}",
        )


class UserDataNotFoundError(UserDataError, FileNotFoundError):
    """Requested user data does not exist."""


class UserDataStore:
    """Store application and game data below two independent confined roots."""

    def __init__(
        self,
        root: Path,
        *,
        application_namespace: str = "application",
        game_namespace: str = "game",
    ) -> None:
        self.root = Path(root).resolve()
        _validate_namespace_name(application_namespace)
        _validate_namespace_name(game_namespace)
        if application_namespace == game_namespace:
            raise ValueError("application and game namespaces must differ")
        self.application_root = self.root / application_namespace
        self.game_root = self.root / game_namespace

    def write_text(
        self,
        relative_path: str | os.PathLike[str],
        payload: str,
        *,
        namespace: UserDataNamespace = "application",
    ) -> None:
        relative = _relative_path(relative_path, "write", namespace)
        target = self._confined_path(relative, namespace, create_root=True)
        try:
            atomic_write_text(target, payload, prefix="expra-user-data-")
        except OSError as error:
            raise UserDataError(
                "User-data write failed",
                operation="write",
                namespace=namespace,
                relative_path=relative,
            ) from error

    def write_bytes(
        self,
        relative_path: str | os.PathLike[str],
        payload: bytes,
        *,
        namespace: UserDataNamespace = "application",
    ) -> None:
        relative = _relative_path(relative_path, "write", namespace)
        target = self._confined_path(relative, namespace, create_root=True)
        try:
            _atomic_write_bytes(target, payload)
        except OSError as error:
            raise UserDataError(
                "User-data write failed",
                operation="write",
                namespace=namespace,
                relative_path=relative,
            ) from error

    def read_text(
        self,
        relative_path: str | os.PathLike[str],
        *,
        namespace: UserDataNamespace = "application",
    ) -> str:
        relative = _relative_path(relative_path, "read", namespace)
        target = self._confined_path(relative, namespace)
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise UserDataNotFoundError(
                "User data was not found",
                operation="read",
                namespace=namespace,
                relative_path=relative,
            ) from error
        except (OSError, UnicodeError) as error:
            raise UserDataError(
                "User-data read failed",
                operation="read",
                namespace=namespace,
                relative_path=relative,
            ) from error

    def read_bytes(
        self,
        relative_path: str | os.PathLike[str],
        *,
        namespace: UserDataNamespace = "application",
    ) -> bytes:
        relative = _relative_path(relative_path, "read", namespace)
        target = self._confined_path(relative, namespace)
        try:
            return target.read_bytes()
        except FileNotFoundError as error:
            raise UserDataNotFoundError(
                "User data was not found",
                operation="read",
                namespace=namespace,
                relative_path=relative,
            ) from error
        except OSError as error:
            raise UserDataError(
                "User-data read failed",
                operation="read",
                namespace=namespace,
                relative_path=relative,
            ) from error

    def delete(
        self,
        relative_path: str | os.PathLike[str],
        *,
        namespace: UserDataNamespace = "application",
    ) -> bool:
        relative = _relative_path(relative_path, "delete", namespace)
        target = self._confined_path(relative, namespace)
        if not target.exists():
            return False
        try:
            target.unlink()
        except OSError as error:
            raise UserDataError(
                "User-data delete failed",
                operation="delete",
                namespace=namespace,
                relative_path=relative,
            ) from error
        return True

    def _confined_path(
        self,
        relative: str,
        namespace: UserDataNamespace,
        *,
        create_root: bool = False,
    ) -> Path:
        base = self.application_root if namespace == "application" else self.game_root
        if create_root:
            try:
                base.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise UserDataError(
                    "User-data root is unavailable",
                    operation="access",
                    namespace=namespace,
                    relative_path=relative,
                ) from error
        _reject_symlink_components(base, relative, namespace)
        candidate = base / relative
        try:
            resolved_base = base.resolve()
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_base)
        except (OSError, ValueError) as error:
            raise UserDataError(
                "User-data path is outside its namespace",
                operation="access",
                namespace=namespace,
                relative_path=relative,
            ) from error
        return candidate


def _validate_namespace_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("user-data namespace must be one path component")


def _relative_path(
    value: str | os.PathLike[str], operation: str, namespace: UserDataNamespace
) -> str:
    relative = os.fspath(value)
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise UserDataError(
            "User-data path is invalid",
            operation=operation,
            namespace=namespace,
            relative_path=_safe_diagnostic_path(str(value)),
        )
    if relative.startswith(("/", "\\")) or _DRIVE_RE.match(relative):
        raise UserDataError(
            "User-data path must be relative",
            operation=operation,
            namespace=namespace,
            relative_path=_safe_diagnostic_path(relative),
        )
    components = relative.split("/")
    if "\\" in relative or any(
        not component or component in {".", ".."} for component in components
    ):
        raise UserDataError(
            "User-data path is invalid",
            operation=operation,
            namespace=namespace,
            relative_path=_safe_diagnostic_path(relative),
        )
    return relative


def _safe_diagnostic_path(value: str) -> str:
    if value.startswith(("/", "\\")) or _DRIVE_RE.match(value):
        return "<absolute-path>"
    return value


def _reject_symlink_components(base: Path, relative: str, namespace: UserDataNamespace) -> None:
    current = base
    if current.is_symlink():
        raise UserDataError(
            "User-data namespace is a symlink",
            operation="access",
            namespace=namespace,
            relative_path=relative,
        )
    for component in relative.split("/"):
        current /= component
        if current.is_symlink():
            raise UserDataError(
                "User-data path contains a symlink",
                operation="access",
                namespace=namespace,
                relative_path=relative,
            )


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix="expra-user-data-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    fsync_directory(path)
