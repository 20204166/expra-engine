"""Renderer-neutral synchronous and coordinated asynchronous resource access."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from expra_engine.coordinators.app_coordinator import AppCoordinator

from .cache import CachePolicy, ContentIdentity, ResourceCache
from .dependencies import DependencyGraph
from .errors import ResourceCancelledError
from .ids import ResourceId
from .mounts import ResourceMount
from .resources import ResourceMetadata, ResourceResolver


class ResourceService:
    """Coordinate resource resolution, value caching, and background reads."""

    def __init__(
        self,
        resolver: ResourceResolver,
        *,
        cache: ResourceCache[bytes] | None = None,
        dependencies: DependencyGraph | None = None,
        coordinator: AppCoordinator | None = None,
    ) -> None:
        self.resolver = resolver
        self.cache = cache or ResourceCache[bytes]()
        self.dependencies = dependencies or DependencyGraph()
        self.coordinator = coordinator

    def metadata(self, resource_id: ResourceId | str) -> ResourceMetadata:
        return self.resolver.resolve(_resource_id(resource_id)).metadata

    def read_bytes(
        self,
        resource_id: ResourceId | str,
        *,
        cache_policy: CachePolicy | None = None,
    ) -> bytes:
        logical_id = _resource_id(resource_id)
        handle = self.resolver.resolve(logical_id)
        identity = ContentIdentity(handle.metadata.size, handle.metadata.content_hash)
        policy = self.cache.policy if cache_policy is None else cache_policy
        if policy is CachePolicy.MEMORY:
            cached = self.cache.get(logical_id, identity)
            if cached is not None:
                return cached
        value = handle.read_bytes()
        if policy in (CachePolicy.MEMORY, CachePolicy.REFRESH):
            self.cache.put(logical_id, value, mount=handle.mount, identity=identity)
        return value

    def read_text(
        self,
        resource_id: ResourceId | str,
        encoding: str = "utf-8",
        errors: str = "strict",
        *,
        cache_policy: CachePolicy | None = None,
    ) -> str:
        return self.read_bytes(resource_id, cache_policy=cache_policy).decode(encoding, errors)

    def open_stream(self, resource_id: ResourceId | str) -> IO[bytes]:
        return self.resolver.resolve(_resource_id(resource_id)).open()

    def read_stream(self, resource_id: ResourceId | str) -> IO[bytes]:
        return self.open_stream(resource_id)

    def register_dependencies(
        self, resource_id: ResourceId | str, dependencies: Iterable[ResourceId | str]
    ) -> None:
        self.dependencies.register(resource_id, dependencies)

    def invalidate(self, resource_id: ResourceId | str) -> set[ResourceId]:
        invalidated = self.dependencies.invalidate(resource_id)
        for item in invalidated:
            self.cache.invalidate(item)
        return invalidated

    def mount(self, mount: ResourceMount) -> None:
        previous = self.resolver.mount_for(mount.spec.name)
        if previous is not None:
            self.cache.invalidate_mount(mount.spec.name)
            close = getattr(previous, "close", None)
            if close is not None:
                close()
        self.resolver.mount(mount)

    def unmount(self, name: str) -> set[ResourceId]:
        invalidated = self.cache.invalidate_mount(name)
        for item in tuple(invalidated):
            invalidated.update(self.invalidate(item))
        mount = self.resolver.mount_for(name)
        self.resolver.unmount(name)
        close = getattr(mount, "close", None)
        if close is not None:
            close()
        return invalidated

    def read_bytes_async(
        self,
        resource_id: ResourceId | str,
        *,
        on_result: Callable[[str, bytes], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        cache_policy: CachePolicy | None = None,
    ) -> int | None:
        if self.coordinator is None:
            raise RuntimeError("async resource loading requires an AppCoordinator")
        logical_id = _resource_id(resource_id)
        key = str(logical_id)

        def load(cancel: threading.Event, _progress: Callable[[str], None]) -> bytes:
            if cancel.is_set():
                raise ResourceCancelledError(operation="read", logical_id=logical_id)
            value = self.read_bytes(logical_id, cache_policy=cache_policy)
            if cancel.is_set():
                raise ResourceCancelledError(operation="read", logical_id=logical_id)
            return value

        return self.coordinator.run(
            key,
            load,
            on_result=on_result,
            on_error=on_error,
            on_finished=on_finished,
        )

    def cancel(self, resource_id: ResourceId | str) -> None:
        if self.coordinator is not None:
            self.coordinator.cancel(str(_resource_id(resource_id)))

    def clear_cache(self) -> set[ResourceId]:
        return self.cache.clear()


def _resource_id(value: ResourceId | str) -> ResourceId:
    return value if isinstance(value, ResourceId) else ResourceId.parse(value)
