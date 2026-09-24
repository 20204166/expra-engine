from __future__ import annotations

import pytest

from expra_engine.coordinators.app_coordinator import AppCoordinator
from expra_engine.filesystem import (
    DirectoryMount,
    MountSpec,
    ResourceId,
    ResourceNotFoundError,
    ResourceResolver,
)
from expra_engine.filesystem.cache import CachePolicy, ContentIdentity, ResourceCache
from expra_engine.filesystem.dependencies import DependencyGraph
from expra_engine.filesystem.errors import (
    DependencyCycleError,
    DependencyError,
    MissingDependencyError,
)
from expra_engine.filesystem.service import ResourceService
from tests.support.scheduling import DeferredRunner, RecordingDelivery


def _id(value: str) -> ResourceId:
    return ResourceId.parse(value)


def test_no_cache_never_returns_or_stores_values() -> None:
    cache: ResourceCache[str] = ResourceCache(CachePolicy.NO_CACHE)
    resource_id = _id("assets://image.png")

    cache.put(resource_id, "decoded", mount="project", identity=ContentIdentity(1, "a"))

    assert cache.get(resource_id, ContentIdentity(1, "a")) is None
    assert cache.invalidate(resource_id) == set()


def test_memory_cache_reuses_only_matching_content_identity() -> None:
    cache: ResourceCache[str] = ResourceCache(CachePolicy.MEMORY)
    resource_id = _id("assets://image.png")
    original = ContentIdentity(1, "a")
    changed = ContentIdentity(2, "b")
    cache.put(resource_id, "decoded", mount="project", identity=original)

    assert cache.get(resource_id, original) == "decoded"
    assert cache.get(resource_id, changed) is None


def test_invalidating_id_disposes_once_and_is_idempotent() -> None:
    disposed: list[str] = []
    cache: ResourceCache[object] = ResourceCache(CachePolicy.MEMORY)
    resource_id = _id("assets://image.png")
    cache.put(
        resource_id,
        object(),
        mount="project",
        identity=ContentIdentity(1, "a"),
        dispose=lambda: disposed.append("disposed"),
    )

    assert cache.invalidate(resource_id) == {resource_id}
    assert cache.invalidate(resource_id) == set()
    assert disposed == ["disposed"]


def test_invalidating_mount_disposes_all_owned_entries() -> None:
    disposed: list[str] = []
    cache: ResourceCache[str] = ResourceCache(CachePolicy.MEMORY)
    for name in ("one", "two"):

        def dispose(name: str = name) -> None:
            disposed.append(name)

        cache.put(
            _id(f"assets://{name}.bin"),
            name,
            mount="archive",
            identity=ContentIdentity(1, name),
            dispose=dispose,
        )
    cache.put(
        _id("assets://other.bin"),
        "other",
        mount="project",
        identity=ContentIdentity(1, "other"),
    )

    invalidated = cache.invalidate_mount("archive")

    assert invalidated == {_id("assets://one.bin"), _id("assets://two.bin")}
    assert sorted(disposed) == ["one", "two"]
    assert cache.get(_id("assets://other.bin"), ContentIdentity(1, "other")) == "other"


def test_dependency_registration_and_reverse_invalidation() -> None:
    graph = DependencyGraph()
    root = _id("assets://root.json")
    child = _id("assets://child.png")
    grandchild = _id("assets://palette.json")
    graph.register(root, [child])
    graph.register(child, [grandchild])

    assert graph.dependencies_of(root) == (child,)
    assert graph.invalidate(grandchild) == {grandchild, child, root}


def test_dependency_registration_reports_missing_dependency() -> None:
    graph = DependencyGraph()
    root = _id("assets://root.json")
    missing = _id("assets://missing.png")

    with pytest.raises(MissingDependencyError):
        graph.register(root, [missing], available={root})


def test_dependency_registration_rejects_cycles_without_mutating_graph() -> None:
    graph = DependencyGraph()
    first = _id("assets://first.json")
    second = _id("assets://second.json")
    graph.register(first, [second])

    with pytest.raises(DependencyCycleError):
        graph.register(second, [first])

    assert graph.dependencies_of(second) == ()


def test_dependency_traversal_is_bounded() -> None:
    graph = DependencyGraph(max_nodes=2)
    first = _id("assets://one")
    second = _id("assets://two")
    third = _id("assets://three")
    graph.register(first, [second])
    graph.register(second, [third])

    with pytest.raises(DependencyError, match="bound"):
        graph.invalidate(third)


def _service(tmp_path, *, runner=None, delivery=None) -> ResourceService:
    (tmp_path / "hello.txt").write_text("hello")
    resolver = ResourceResolver(
        [DirectoryMount(tmp_path, MountSpec(name="project", scheme="assets"))]
    )
    coordinator = (
        AppCoordinator(runner=runner, deliver=delivery)
        if runner is not None or delivery is not None
        else None
    )
    return ResourceService(resolver, coordinator=coordinator)


def test_service_reads_bytes_text_stream_and_metadata(tmp_path) -> None:
    service = _service(tmp_path)
    resource_id = _id("assets://hello.txt")

    assert service.read_bytes(resource_id) == b"hello"
    assert service.read_text(resource_id) == "hello"
    with service.open_stream(resource_id) as stream:
        assert stream.read() == b"hello"
    assert service.metadata(resource_id).size == 5


def test_service_no_cache_bypasses_memory_cache(tmp_path) -> None:
    service = _service(tmp_path)
    resource_id = _id("assets://hello.txt")

    first = service.read_bytes(resource_id, cache_policy=CachePolicy.MEMORY)
    assert first == b"hello"
    (tmp_path / "hello.txt").write_text("changed")

    assert service.read_bytes(resource_id, cache_policy=CachePolicy.MEMORY) == b"changed"
    assert service.read_bytes(resource_id, cache_policy=CachePolicy.NO_CACHE) == b"changed"


def test_read_bytes_async_without_coordinator_raises(tmp_path) -> None:
    service = _service(tmp_path)

    with pytest.raises(RuntimeError):
        service.read_bytes_async(_id("assets://hello.txt"))


def test_clear_cache_drops_memory_entries_but_not_disk_content(tmp_path) -> None:
    service = _service(tmp_path)
    resource_id = _id("assets://hello.txt")
    service.read_bytes(resource_id, cache_policy=CachePolicy.MEMORY)

    invalidated = service.clear_cache()

    assert invalidated == {resource_id}
    assert service.read_bytes(resource_id) == b"hello"


def test_remounting_same_name_invalidates_previous_cache_and_closes_it(tmp_path) -> None:
    service = _service(tmp_path)
    resource_id = _id("assets://hello.txt")
    service.read_bytes(resource_id, cache_policy=CachePolicy.MEMORY)
    (tmp_path / "hello.txt").write_text("replaced")

    service.mount(DirectoryMount(tmp_path, MountSpec(name="project", scheme="assets")))

    assert service.read_bytes(resource_id, cache_policy=CachePolicy.MEMORY) == b"replaced"


def test_unmount_invalidates_cache_and_closes_mount(tmp_path) -> None:
    service = _service(tmp_path)
    resource_id = _id("assets://hello.txt")
    service.read_bytes(resource_id)

    invalidated = service.unmount("project")

    assert invalidated == {resource_id}
    with pytest.raises(ResourceNotFoundError):
        service.read_bytes(resource_id)


def test_async_read_delivers_through_coordinator(tmp_path) -> None:
    runner = DeferredRunner()
    delivery = RecordingDelivery()
    service = _service(tmp_path, runner=runner, delivery=delivery)
    values: list[bytes] = []

    generation = service.read_bytes_async(
        _id("assets://hello.txt"), on_result=lambda _key, value: values.append(value)
    )

    assert generation == 1
    runner.run_next()
    assert values == []
    delivery.flush()
    assert values == [b"hello"]


def test_async_cancel_drops_stale_result(tmp_path) -> None:
    runner = DeferredRunner()
    delivery = RecordingDelivery()
    service = _service(tmp_path, runner=runner, delivery=delivery)
    values: list[bytes] = []
    resource_id = _id("assets://hello.txt")

    service.read_bytes_async(resource_id, on_result=lambda _key, value: values.append(value))
    service.cancel(resource_id)
    runner.run_next()
    delivery.flush()

    assert values == []


def test_async_result_from_old_generation_is_ignored(tmp_path) -> None:
    runner = DeferredRunner()
    delivery = RecordingDelivery()
    service = _service(tmp_path, runner=runner, delivery=delivery)
    values: list[bytes] = []
    resource_id = _id("assets://hello.txt")
    key = str(resource_id)

    service.read_bytes_async(resource_id, on_result=lambda _key, value: values.append(value))
    runner.run_next()
    assert service.coordinator is not None
    service.coordinator.state(key).generation += 1
    delivery.flush()

    assert values == []
