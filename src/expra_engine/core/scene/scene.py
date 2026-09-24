"""Scene — entity container with serialization.

A Scene has a stable UUID, a name, and an ordered list of entities.
Scenes serialize to/from JSON-friendly dicts. Round-trips must preserve
all entity IDs and component state.
"""

from __future__ import annotations

import contextlib
import copy
import math
import uuid
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene.camera import SceneCamera


def _clone_components_and_tags(source: Entity, target: Entity) -> None:
    """Deep-copy *source*'s components and tags into *target*."""
    for comp in source.components:
        target.add_component(copy.deepcopy(comp))
    for tag in source.tags:
        target.add_tag(tag)


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
        camera: dict[str, Any] | SceneCamera | None = None,
    ) -> None:
        self.scene_id: str = scene_id or str(uuid.uuid4())
        self.name = name
        self._camera = camera if isinstance(camera, SceneCamera) else SceneCamera(camera)
        self._entities: list[Entity] = []

    @property
    def entities(self) -> tuple[Entity, ...]:
        return tuple(self._entities)

    @property
    def camera(self) -> SceneCamera:
        return self._camera

    @camera.setter
    def camera(self, value: dict[str, Any] | SceneCamera) -> None:
        self._camera = value if isinstance(value, SceneCamera) else SceneCamera(value)

    def create_entity(self, name: str, **kwargs: Any) -> Entity:
        """Create and register a new entity, returning it."""
        entity = Entity(name, **kwargs)
        self.add_entity(entity)
        return entity

    def add_entity(self, entity: Entity) -> None:
        """Register an already-constructed entity."""
        if self.find_entity(entity.entity_id) is not None:
            raise ValueError(f"Entity ID already exists in scene: {entity.entity_id!r}")
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
            _clone_components_and_tags(root, new_root)
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
            _clone_components_and_tags(original, cloned)
            self.add_entity(cloned)

        return self.find_entity(id_map[entity_id])

    def find_entity(self, entity_id: str) -> Entity | None:
        """Return entity by ID, or None."""
        for entity in self._entities:
            if entity.entity_id == entity_id:
                return entity
        return None

    def world_pose(self, entity_id: str) -> tuple[float, float, float]:
        """Return an entity's authoritative parent-composed 2D pose.

        Missing or disabled transforms use the identity pose, matching render
        extraction. Missing parents are treated as roots; malformed cycles are
        rejected rather than recursing indefinitely.
        """
        entities = {entity.entity_id: entity for entity in self._entities}
        active: set[str] = set()

        def resolve(current_id: str) -> tuple[float, float, float, float, float]:
            if current_id in active:
                raise ValueError("entity hierarchy contains a cycle")
            entity = entities.get(current_id)
            if entity is None:
                raise KeyError(f"entity not found: {current_id!r}")
            active.add(current_id)
            transform = entity.get_component(TransformComponent)
            if transform is None or not transform.enabled:
                local = (0.0, 0.0, 0.0, 1.0, 1.0)
            else:
                values: tuple[float, float, float, float, float] = (
                    float(transform.x),
                    float(transform.y),
                    float(transform.rotation),
                    float(transform.scale_x),
                    float(transform.scale_y),
                )
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("transform values must be finite")
                local = values
            x, y, rotation, scale_x, scale_y = local
            parent = entities.get(entity.parent_id) if entity.parent_id is not None else None
            if parent is not None:
                px, py, protation, pscale_x, pscale_y = resolve(parent.entity_id)
                angle = math.radians(protation)
                x, y = (
                    px + (x * pscale_x) * math.cos(angle) - (y * pscale_y) * math.sin(angle),
                    py + (x * pscale_x) * math.sin(angle) + (y * pscale_y) * math.cos(angle),
                )
                rotation += protation
                scale_x *= pscale_x
                scale_y *= pscale_y
            active.remove(current_id)
            return x, y, rotation, scale_x, scale_y

        x, y, rotation, _scale_x, _scale_y = resolve(entity_id)
        return x, y, rotation

    def entities_by_layer(self) -> list[Entity]:
        """Return all entities sorted ascending by layer."""
        return sorted(self._entities, key=lambda entity: entity.layer)

    def find_entity_by_name(self, name: str) -> Entity | None:
        for entity in self._entities:
            if entity.name == name:
                return entity
        return None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "scene_id": self.scene_id,
            "name": self.name,
            "entities": [e.to_dict() for e in self._entities],
        }
        if self.camera:
            data["camera"] = self.camera.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        camera = data.get("camera")
        scene = cls(
            name=str(data["name"]),
            scene_id=str(data["scene_id"]),
            camera=camera if isinstance(camera, dict) else None,
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
        return tuple(
            e
            for e in self._entities
            if (tag is None or e.has_tag(tag))
            and (component is None or e.get_component(component) is not None)
        )
