"""Renderer-neutral resource value caching and lifecycle ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from .ids import ResourceId

T = TypeVar("T")


class CachePolicy(StrEnum):
    """Cache behavior for resource loads."""

    NO_CACHE = "no-cache"
    MEMORY = "memory"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Stable identity for the bytes represented by a resource."""

    size: int
    sha256: str


@dataclass(slots=True)
class CacheEntry[T]:
    """A cached value and the ownership information needed to release it."""

    logical_id: ResourceId
    mount: str
    identity: ContentIdentity
    value: T
    dispose: Callable[[], None] | None = None
    _disposed: bool = False

    def release(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        if self.dispose is not None:
            self.dispose()


class ResourceCache[T]:
    """An explicit no-cache or in-memory cache for decoded resource values."""

    def __init__(self, policy: CachePolicy = CachePolicy.MEMORY) -> None:
        self.policy = policy
        self._entries: dict[ResourceId, CacheEntry[T]] = {}

    def get(self, logical_id: ResourceId, identity: ContentIdentity) -> T | None:
        if self.policy is CachePolicy.NO_CACHE:
            return None
        entry = self._entries.get(logical_id)
        if entry is None:
            return None
        if entry.identity != identity:
            self._remove(logical_id)
            return None
        return entry.value

    def put(
        self,
        logical_id: ResourceId,
        value: T,
        *,
        mount: str,
        identity: ContentIdentity,
        dispose: Callable[[], None] | None = None,
    ) -> CacheEntry[T] | None:
        if self.policy is CachePolicy.NO_CACHE:
            return None
        self._remove(logical_id)
        entry = CacheEntry(logical_id, mount, identity, value, dispose)
        self._entries[logical_id] = entry
        return entry

    def invalidate(self, logical_id: ResourceId) -> set[ResourceId]:
        if logical_id not in self._entries:
            return set()
        self._remove(logical_id)
        return {logical_id}

    def invalidate_mount(self, mount: str) -> set[ResourceId]:
        invalidated = {
            logical_id for logical_id, entry in self._entries.items() if entry.mount == mount
        }
        for logical_id in invalidated:
            self._remove(logical_id)
        return invalidated

    def clear(self) -> set[ResourceId]:
        invalidated = set(self._entries)
        for logical_id in tuple(invalidated):
            self._remove(logical_id)
        return invalidated

    def _remove(self, logical_id: ResourceId) -> None:
        entry = self._entries.pop(logical_id, None)
        if entry is not None:
            entry.release()
