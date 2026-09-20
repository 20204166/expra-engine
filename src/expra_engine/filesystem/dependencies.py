"""Directed logical-resource dependency graphs."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import DependencyCycleError, DependencyError, MissingDependencyError
from .ids import ResourceId


class DependencyGraph:
    """Track resource dependencies and efficiently find reverse invalidations."""

    def __init__(self, *, max_nodes: int = 1024) -> None:
        if max_nodes < 1:
            raise ValueError("max_nodes must be positive")
        self.max_nodes = max_nodes
        self._dependencies: dict[ResourceId, set[ResourceId]] = {}
        self._dependents: dict[ResourceId, set[ResourceId]] = {}

    def register(
        self,
        resource_id: ResourceId | str,
        dependencies: Iterable[ResourceId | str],
        *,
        available: Iterable[ResourceId | str] | None = None,
    ) -> None:
        resource_id = _resource_id(resource_id)
        dependency_set = {_resource_id(dependency) for dependency in dependencies}
        if available is not None:
            available_ids = {_resource_id(item) for item in available}
            missing = sorted(dependency_set - available_ids, key=str)
            if missing:
                raise MissingDependencyError(
                    "Dependency is not available",
                    operation="register",
                    logical_id=missing[0],
                )
        if resource_id in dependency_set or any(
            self._depends_on(dependency, resource_id) for dependency in dependency_set
        ):
            raise DependencyCycleError(
                "Registering dependencies would create a cycle",
                operation="register",
                logical_id=resource_id,
            )

        old_dependencies = self._dependencies.get(resource_id, set())
        for dependency in old_dependencies - dependency_set:
            self._dependents[dependency].discard(resource_id)
        self._dependencies[resource_id] = dependency_set
        for dependency in dependency_set:
            self._dependents.setdefault(dependency, set()).add(resource_id)

    def dependencies_of(self, resource_id: ResourceId | str) -> tuple[ResourceId, ...]:
        return tuple(sorted(self._dependencies.get(_resource_id(resource_id), set()), key=str))

    def dependents_of(self, resource_id: ResourceId | str) -> tuple[ResourceId, ...]:
        return tuple(sorted(self._dependents.get(_resource_id(resource_id), set()), key=str))

    def invalidate(self, resource_id: ResourceId | str) -> set[ResourceId]:
        """Return the resource and every registered resource depending on it."""
        root = _resource_id(resource_id)
        invalidated: set[ResourceId] = set()
        pending = [root]
        while pending:
            current = pending.pop()
            if current in invalidated:
                continue
            invalidated.add(current)
            if len(invalidated) > self.max_nodes:
                raise DependencyError(
                    "Dependency invalidation exceeded traversal bound",
                    operation="invalidate",
                    logical_id=root,
                )
            pending.extend(self._dependents.get(current, ()))
        return invalidated

    def transitive_dependencies(
        self,
        resource_id: ResourceId | str,
        *,
        available: Iterable[ResourceId | str] | None = None,
    ) -> set[ResourceId]:
        """Return all dependencies, checking availability and traversal bounds."""
        root = _resource_id(resource_id)
        available_ids = None if available is None else {_resource_id(item) for item in available}
        found: set[ResourceId] = set()
        pending = list(self._dependencies.get(root, ()))
        while pending:
            current = pending.pop()
            if current in found:
                continue
            if available_ids is not None and current not in available_ids:
                raise MissingDependencyError(
                    "Dependency is not available",
                    operation="resolve-dependencies",
                    logical_id=current,
                )
            found.add(current)
            if len(found) > self.max_nodes:
                raise DependencyError(
                    "Dependency traversal exceeded traversal bound",
                    operation="resolve-dependencies",
                    logical_id=root,
                )
            pending.extend(self._dependencies.get(current, ()))
        return found

    def _depends_on(self, start: ResourceId, target: ResourceId) -> bool:
        pending = [start]
        visited: set[ResourceId] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(self._dependencies.get(current, ()))
        return False


def _resource_id(value: ResourceId | str) -> ResourceId:
    if isinstance(value, ResourceId):
        return value
    return ResourceId.parse(value)
