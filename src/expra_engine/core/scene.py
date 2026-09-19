"""Scene — entity container with serialization.

A Scene has a stable UUID, a name, and an ordered list of entities.
Scenes serialize to/from JSON-friendly dicts. Round-trips must preserve
all entity IDs and component state.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from expra_engine.core.entity import Entity


class Scene:
    """Container for entities that make up one game level or screen.

    Supports:
    - create_entity / remove_entity / find_entity
    - to_dict / from_dict (JSON-round-trippable)
    """

    def __init__(
        self,
        name: str,
        *,
        scene_id: str | None = None,
    ) -> None:
        self.scene_id: str = scene_id or str(uuid.uuid4())
        self.name = name
        self._entities: list[Entity] = []

    @property
    def entities(self) -> tuple[Entity, ...]:
        return tuple(self._entities)

    def create_entity(self, name: str, **kwargs: Any) -> Entity:
        """Create and register a new entity, returning it."""
        entity = Entity(name, **kwargs)
        self._entities.append(entity)
        return entity

    def add_entity(self, entity: Entity) -> None:
        """Register an already-constructed entity."""
        self._entities.append(entity)

    def remove_entity(self, entity_id: str) -> bool:
        """Remove entity by ID. Returns True if found and removed."""
        for i, entity in enumerate(self._entities):
            if entity.entity_id == entity_id:
                self._entities.pop(i)
                return True
        return False

    def find_entity(self, entity_id: str) -> Entity | None:
        """Return entity by ID, or None."""
        for entity in self._entities:
            if entity.entity_id == entity_id:
                return entity
        return None

    def find_entity_by_name(self, name: str) -> Entity | None:
        for entity in self._entities:
            if entity.name == name:
                return entity
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "entities": [e.to_dict() for e in self._entities],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        scene = cls(
            name=str(data["name"]),
            scene_id=str(data["scene_id"]),
        )
        for entity_data in data.get("entities", []):
            with contextlib.suppress(KeyError, TypeError):
                scene.add_entity(Entity.from_dict(entity_data))
        return scene

    def __repr__(self) -> str:
        return f"Scene({self.name!r}, id={self.scene_id!r}, entities={len(self._entities)})"
