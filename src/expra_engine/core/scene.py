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

    def remove_entity(self, entity_id: str, *, recursive: bool = False) -> bool:
        """Remove entity by ID. Returns True if found and removed.

        When *recursive* is True all descendant entities are removed first
        (depth-first), so no dangling parent_id references remain.
        """
        if recursive:
            subtree = self.walk_hierarchy(entity_id)
            if not subtree:
                return False
            ids_to_remove = {e.entity_id for e in subtree}
            self._entities = [e for e in self._entities if e.entity_id not in ids_to_remove]
            return True
        for i, entity in enumerate(self._entities):
            if entity.entity_id == entity_id:
                self._entities.pop(i)
                return True
        return False

    def clone_entity(self, entity_id: str, *, recursive: bool = True) -> Entity | None:
        """Clone an entity (and optionally its descendants) into this scene.

        All cloned entities receive new UUIDs.  Source entities are never
        mutated.  Parent-child relationships within the cloned subtree are
        remapped to the new IDs; children of the cloned root are re-parented
        to the new root ID.

        Returns the new root entity, or None when *entity_id* is not found.
        """
        import copy as _copy

        root = self.find_entity(entity_id)
        if root is None:
            return None

        if not recursive:
            new_root = Entity(
                root.name,
                enabled=root.enabled,
                layer=root.layer,
                parent_id=root.parent_id,
            )
            for comp in root.components:
                new_root.add_component(_copy.deepcopy(comp))
            for tag in root.tags:
                new_root.add_tag(tag)
            self.add_entity(new_root)
            return new_root

        subtree = self.walk_hierarchy(entity_id)
        id_map: dict[str, str] = {}
        for original in subtree:
            id_map[original.entity_id] = str(uuid.uuid4())

        for original in subtree:
            new_id = id_map[original.entity_id]
            new_parent_id = (
                id_map.get(original.parent_id) if original.parent_id else original.parent_id
            )
            cloned = Entity(
                original.name,
                entity_id=new_id,
                enabled=original.enabled,
                layer=original.layer,
                parent_id=new_parent_id,
            )
            for comp in original.components:
                cloned.add_component(_copy.deepcopy(comp))
            for tag in original.tags:
                cloned.add_tag(tag)
            self.add_entity(cloned)

        return self.find_entity(id_map[entity_id])

    def find_entity(self, entity_id: str) -> Entity | None:
        """Return entity by ID, or None."""
        for entity in self._entities:
            if entity.entity_id == entity_id:
                return entity
        return None

    def entities_by_layer(self) -> list[Entity]:
        """Return all entities sorted ascending by layer."""
        return sorted(self._entities, key=lambda entity: entity.layer)

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

    # ------------------------------------------------------------------
    # Hierarchy operations
    # ------------------------------------------------------------------

    def children_of(self, parent_id: str) -> list[Entity]:
        """Return direct children of the entity with ``parent_id``."""
        return [e for e in self._entities if e.parent_id == parent_id]

    def roots(self) -> list[Entity]:
        """Return top-level entities (those with no parent)."""
        return [e for e in self._entities if e.parent_id is None]

    def set_entity_parent(self, entity_id: str, parent_id: str | None) -> None:
        """Set the parent of entity ``entity_id`` to ``parent_id``.

        Raises ValueError if:
          - either entity is not in the scene
          - the entity would become its own parent
          - setting the parent would create a cycle
        """
        if parent_id is not None and entity_id == parent_id:
            raise ValueError(f"Entity {entity_id!r} cannot be its own parent")
        child = self.find_entity(entity_id)
        if child is None:
            raise ValueError(f"Entity not found: {entity_id!r}")
        if parent_id is not None:
            if self.find_entity(parent_id) is None:
                raise ValueError(f"Parent entity not found: {parent_id!r}")
            if self._would_create_cycle(entity_id, parent_id):
                raise ValueError(
                    f"Setting parent {parent_id!r} on {entity_id!r} would create a cycle"
                )
        child.parent_id = parent_id

    def _would_create_cycle(self, entity_id: str, proposed_parent_id: str) -> bool:
        """Return True if making proposed_parent_id a parent of entity_id creates a cycle."""
        visited: set[str] = set()
        current: str | None = proposed_parent_id
        while current is not None:
            if current == entity_id:
                return True
            if current in visited:
                break
            visited.add(current)
            ancestor = self.find_entity(current)
            current = ancestor.parent_id if ancestor else None
        return False

    def walk_hierarchy(self, root_id: str | None = None) -> list[Entity]:
        """Depth-first traversal of the entity hierarchy.

        If ``root_id`` is given, traverses the subtree rooted there.
        If ``root_id`` is None, traverses all root-level entities and their
        subtrees in order.

        Adapted from ppb/gomlib.py walk() (PursuedPyBear, Artistic License 2.0).
        """
        from collections import deque

        result: list[Entity] = []
        if root_id is not None:
            root = self.find_entity(root_id)
            if root is None:
                return []
            starts = [root]
        else:
            starts = self.roots()

        queue: deque[Entity] = deque(starts)
        while queue:
            entity = queue.popleft()
            result.append(entity)
            for child in self.children_of(entity.entity_id):
                queue.append(child)
        return result

    # ------------------------------------------------------------------
    # Tag and component queries (analogous to PPB Children.get())
    # ------------------------------------------------------------------

    def get_entities_by_tag(self, tag: str) -> tuple[Entity, ...]:
        """Return all entities that have ``tag``."""
        return tuple(e for e in self._entities if e.has_tag(tag))

    def get_entities_by_component(self, cls: type) -> tuple[Entity, ...]:
        """Return all entities that have at least one component of type ``cls``."""
        return tuple(e for e in self._entities if e.get_component(cls) is not None)

    def get_entities(
        self, *, tag: str | None = None, component: type | None = None
    ) -> tuple[Entity, ...]:
        """Flexible query combining tag and/or component filter.

        Analogous to PPB Children.get(kind=..., tag=...) but using Expra's
        component model instead of inheritance-based kinds.

        Passing neither ``tag`` nor ``component`` raises TypeError.
        """
        if tag is None and component is None:
            raise TypeError(
                "get_entities() requires at least 'tag' or 'component' keyword argument"
            )
        candidates: set[Entity] | None = None
        if tag is not None:
            candidates = {e for e in self._entities if e.has_tag(tag)}
        if component is not None:
            by_comp = {e for e in self._entities if e.get_component(component) is not None}
            candidates = by_comp if candidates is None else candidates & by_comp
        assert candidates is not None
        return tuple(e for e in self._entities if e in candidates)
