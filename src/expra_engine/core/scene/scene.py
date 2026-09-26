"""Scene — entity container with serialization.

A Scene has a stable UUID, a name, and an ordered list of entities.
Scenes serialize to/from JSON-friendly dicts. Round-trips must preserve
all entity IDs and component state.
"""

from __future__ import annotations

import copy
import math
import uuid
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.entity import Entity
from expra_engine.core.math_utils import compose_2d_pose
from expra_engine.core.scene.camera import SceneCamera
from expra_engine.observability import ObservabilityWatcher, observe_stage


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

    document_kind = DocumentKind.SCENE

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
        # Instance-root entity_id -> materialized descendant entity_ids. Purely
        # runtime bookkeeping (never serialized): lets Project.save_scene omit
        # resolve-from-source content and lets the editor mark it read-only-ish.
        self._instance_children: dict[str, set[str]] = {}
        # Lazy parent_id -> children derived index (never serialized). Measured
        # (Phase H): children_of()'s naive O(n) scan dominates walk_hierarchy()
        # (76% of its cost at 1000 entities, cProfile-confirmed) and made
        # HierarchyPanel.render() scale super-linearly (~61ms/~73ms at 1000
        # entities, from ~3ms/~2ms at 100) -- genuine, measured pain at the
        # spec's own test ceiling, not merely theoretical. Invalidated (set to
        # None) by every structural mutation; rebuilt in one O(n) pass on next
        # read. children_of() keeps returning a fresh list per call (copies
        # out of the index) so callers can never mutate cached state.
        self._children_index: dict[str | None, list[Entity]] | None = None
        # Lazy entity_id -> Entity index (never serialized). find_entity() was a
        # linear scan, so add_entity()'s duplicate check made building or
        # materializing N entities O(N^2) -- measured (Phase H) at ~12x cost per
        # 4x reusable scene instances, and it also made HierarchyPanel.render()
        # O(N^2) via its per-entity find_entity() calls. Kept incrementally in
        # sync by add_entity/remove_entity so it never rebuilds in a hot loop.
        self._entity_index: dict[str, Entity] | None = None

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
        index = self._ensure_entity_index()
        if entity.entity_id in index:
            raise ValueError(f"Entity ID already exists in scene: {entity.entity_id!r}")
        self._entities.append(entity)
        index[entity.entity_id] = entity
        if self._children_index is not None:
            # Keep an already-built children index in sync incrementally rather
            # than discarding it and forcing an O(n) rebuild on the next
            # children_of() -- that rebuild-on-every-add made resolving many
            # scene instances O(n^2) (a full index rebuild per materialized
            # entity's following walk_hierarchy()).
            self._children_index.setdefault(entity.parent_id, []).append(entity)

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
            if self._entity_index is not None:
                for removed_id in ids_to_remove:
                    self._entity_index.pop(removed_id, None)
            self._forget_instance_bookkeeping(ids_to_remove)
            self._children_index = None
            return True
        for i, entity in enumerate(self._entities):
            if entity.entity_id == entity_id:
                self._entities.pop(i)
                if self._entity_index is not None:
                    self._entity_index.pop(entity_id, None)
                self._forget_instance_bookkeeping({entity_id})
                self._children_index = None
                return True
        return False

    def _forget_instance_bookkeeping(self, removed_ids: set[str]) -> None:
        """Drop any scene-instance tracking that referenced a removed entity."""
        for root_id in removed_ids:
            self._instance_children.pop(root_id, None)
        for children in self._instance_children.values():
            children -= removed_ids

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
        """Return entity by ID, or None (O(1) via the lazy entity index)."""
        return self._ensure_entity_index().get(entity_id)

    def _ensure_entity_index(self) -> dict[str, Entity]:
        """Build the lazy entity_id -> Entity index if it does not exist yet."""
        if self._entity_index is None:
            self._entity_index = {entity.entity_id: entity for entity in self._entities}
        return self._entity_index

    def world_pose(self, entity_id: str) -> tuple[float, float, float]:
        """Return an entity's authoritative parent-composed 2D pose.

        Missing or disabled transforms use the identity pose, matching render
        extraction. Missing parents are treated as roots; malformed cycles are
        rejected rather than recursing indefinitely.
        """
        entities = self._ensure_entity_index()
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
            parent = entities.get(entity.parent_id) if entity.parent_id is not None else None
            pose = local
            if parent is not None:
                pose = compose_2d_pose(resolve(parent.entity_id), local)
            active.remove(current_id)
            return pose

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

    def to_dict(self, *, include_instance_content: bool = True) -> dict[str, Any]:
        """Serialize this scene.

        ``include_instance_content=False`` omits entities materialized by
        scene-instance resolution (see ``is_instance_materialized``) -- used
        by ``Project.save_scene`` so resolve-from-source content is never
        persisted. Every other caller (runtime scene copies, export, tests)
        keeps the default, full snapshot.
        """
        entities = self._entities
        if not include_instance_content:
            # One union instead of calling is_instance_materialized() per entity
            # (that is O(instance-roots) each, making compact serialization
            # O(entities * instances) -- measured 3.2ms->53ms from 100->400
            # instances before this).
            materialized = {
                entity_id for children in self._instance_children.values() for entity_id in children
            }
            entities = [e for e in entities if e.entity_id not in materialized]
        data: dict[str, Any] = {
            "scene_id": self.scene_id,
            "name": self.name,
            "entities": [e.to_dict() for e in entities],
        }
        if self.camera:
            data["camera"] = self.camera.to_dict()
        return data

    # ------------------------------------------------------------------
    # Scene-instance bookkeeping (see core/scene/scene_instance.py)
    # ------------------------------------------------------------------

    def is_instance_materialized(self, entity_id: str) -> bool:
        """Return True if ``entity_id`` was materialized by scene-instance resolution."""
        return any(entity_id in children for children in self._instance_children.values())

    def _set_instance_children(self, root_id: str, entity_ids: set[str]) -> None:
        """Record which entity ids were materialized under instance root ``root_id``."""
        self._instance_children[root_id] = set(entity_ids)

    def _clear_instance_subtree(self, root_id: str) -> None:
        """Remove every current descendant of ``root_id`` before re-resolving it.

        Removes the *entire* current subtree, not just previously-tracked
        materialized ids -- resolving a scene instance always fully replaces
        whatever is under its root (matching Godot's instantiate()
        semantics), so a root cloned via ``Scene.clone_entity`` (whose
        snapshot children are not yet tracked) still re-links cleanly on the
        next resolve instead of accumulating duplicates.
        """
        stale_entities = [e for e in self.walk_hierarchy(root_id) if e.entity_id != root_id]
        if not stale_entities:
            self._instance_children.pop(root_id, None)
            return
        stale = {e.entity_id for e in stale_entities}
        self._entities = [e for e in self._entities if e.entity_id not in stale]
        if self._entity_index is not None:
            for removed in stale_entities:
                self._entity_index.pop(removed.entity_id, None)
        if self._children_index is not None:
            # Prune surgically instead of dropping the whole index: this runs
            # once per instance during re-resolve, so a wholesale rebuild here
            # would make re-resolving many instances O(n^2).
            for removed in stale_entities:
                bucket = self._children_index.get(removed.parent_id)
                if bucket is not None:
                    bucket[:] = [child for child in bucket if child.entity_id != removed.entity_id]
                self._children_index.pop(removed.entity_id, None)
        self._forget_instance_bookkeeping(stale)
        self._instance_children.pop(root_id, None)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        observer: ObservabilityWatcher | None = None,
    ) -> Scene:
        camera = data.get("camera")
        scene = cls(
            name=str(data["name"]),
            scene_id=str(data["scene_id"]),
            camera=camera if isinstance(camera, dict) else None,
        )
        entity_data_list = data.get("entities", [])
        if not isinstance(entity_data_list, list):
            raise ValueError("document entities must be a list")
        staged: list[tuple[Entity, dict[str, Any]]] = []
        with observe_stage(observer, "document:construct:entities"):
            for entity_data in entity_data_list:
                if not isinstance(entity_data, dict):
                    raise ValueError("document entity must be an object")
                try:
                    staged.append(
                        (Entity.from_dict(entity_data, include_components=False), entity_data)
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"invalid entity: {exc}") from exc
        with observe_stage(observer, "document:construct:components"):
            for entity, entity_data in staged:
                entity._restore_components(entity_data)
        with observe_stage(observer, "document:construct:hierarchy"):
            for entity, _entity_data in staged:
                scene.add_entity(entity)
            scene._validate_hierarchy()
        return scene

    def _validate_hierarchy(self) -> None:
        """Reject dangling parents and cycles before a loaded scene is exposed."""
        entities = self._ensure_entity_index()
        for entity in self._entities:
            if entity.parent_id is not None and entity.parent_id not in entities:
                raise ValueError(
                    f"entity {entity.entity_id!r} has missing parent {entity.parent_id!r}"
                )

        state: dict[str, int] = {}
        for start in entities:
            current: str | None = start
            trail: list[str] = []
            while current is not None and state.get(current, 0) == 0:
                state[current] = 1
                trail.append(current)
                current = entities[current].parent_id
            if current is not None and state.get(current) == 1:
                raise ValueError("entity hierarchy contains a cycle")
            for entity_id in trail:
                state[entity_id] = 2

    def __repr__(self) -> str:
        return f"Scene({self.name!r}, id={self.scene_id!r}, entities={len(self._entities)})"

    # ------------------------------------------------------------------
    # Hierarchy operations
    # ------------------------------------------------------------------

    def children_of(self, parent_id: str) -> list[Entity]:
        """Return direct children of the entity with ``parent_id``.

        Served from a lazy derived index (parent_id -> children), rebuilt in
        one O(n) pass whenever stale -- see the ``_children_index`` comment
        in ``__init__`` for the measurement that motivated this. Always
        returns a fresh list, never the cached list itself, so callers can
        never mutate cached state.
        """
        return list(self._ensure_children_index().get(parent_id, ()))

    def _ensure_children_index(self) -> dict[str | None, list[Entity]]:
        """Build the derived parent index once for internal and public reads."""
        if self._children_index is None:
            index: dict[str | None, list[Entity]] = {}
            for entity in self._entities:
                index.setdefault(entity.parent_id, []).append(entity)
            self._children_index = index
        return self._children_index

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
        self._children_index = None

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
        result: list[Entity] = []
        if root_id is not None:
            root = self.find_entity(root_id)
            if root is None:
                return []
            starts = [root]
        else:
            starts = self.roots()

        children_index = self._ensure_children_index()
        queue = list(starts)
        cursor = 0
        while cursor < len(queue):
            entity = queue[cursor]
            cursor += 1
            result.append(entity)
            queue.extend(children_index.get(entity.entity_id, ()))
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
