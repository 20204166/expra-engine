"""Entity — a named game object with components.

Entities have stable UUIDs, a name, an enabled flag, and an ordered list of
components. Hierarchy (parent/child) is supported via optional parent_id.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any, TypeVar

from expra_engine.core.component import Component, component_from_dict

C = TypeVar("C", bound=Component)


class Entity:
    """A named game object that holds components.

    ``entity_id`` is a stable UUID string. IDs survive serialization
    round-trips; never regenerate them on load.
    """

    def __init__(
        self,
        name: str,
        *,
        entity_id: str | None = None,
        enabled: bool = True,
        parent_id: str | None = None,
    ) -> None:
        self.entity_id: str = entity_id or str(uuid.uuid4())
        self.name = name
        self.enabled = enabled
        self.parent_id = parent_id
        self._components: list[Component] = []
        self._tags: set[str] = set()

    @property
    def components(self) -> tuple[Component, ...]:
        return tuple(self._components)

    def add_component(self, component: Component) -> None:
        self._components.append(component)

    def remove_component(self, component: Component) -> bool:
        try:
            self._components.remove(component)
            return True
        except ValueError:
            return False

    def get_component(self, cls: type[C]) -> C | None:
        for component in self._components:
            if isinstance(component, cls):
                return component
        return None

    def get_components(self, cls: type[C]) -> list[C]:
        return [c for c in self._components if isinstance(c, cls)]

    @property
    def tags(self) -> frozenset[str]:
        """The set of tags on this entity (immutable view)."""
        return frozenset(self._tags)

    def add_tag(self, tag: str) -> None:
        """Add a tag to this entity."""
        self._tags.add(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag; no-op if absent."""
        self._tags.discard(tag)

    def has_tag(self, tag: str) -> bool:
        """Return True if this entity has the given tag."""
        return tag in self._tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "enabled": self.enabled,
            "parent_id": self.parent_id,
            "components": [c.to_dict() for c in self._components],
            "tags": sorted(self._tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entity:
        entity = cls(
            name=str(data["name"]),
            entity_id=str(data["entity_id"]),
            enabled=bool(data.get("enabled", True)),
            parent_id=data.get("parent_id"),
        )
        for tag in data.get("tags", []):
            entity.add_tag(str(tag))
        for component_data in data.get("components", []):
            with contextlib.suppress(ValueError, KeyError):
                entity.add_component(component_from_dict(component_data))
        return entity

    def __repr__(self) -> str:
        return f"Entity({self.name!r}, id={self.entity_id!r})"
