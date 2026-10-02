"""Scene — entity container with serialization.

A Scene has a stable UUID, a name, and an ordered list of entities.
Scenes serialize to/from JSON-friendly dicts. Round-trips must preserve
all entity IDs and component state.
"""

from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import Component, TransformComponent
from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.entity import Entity
from expra_engine.core.math_utils import compose_2d_pose
from expra_engine.core.scene.camera import SceneCamera
from expra_engine.observability import ObservabilityWatcher, observe_stage

_ENTITY_EVENT_HANDLER_NAMES = ("on_action_event", "on_frame_update", "on_idle", "on_update")
_BASE_ENTITY_EVENT_HANDLERS = {
    name: getattr(Entity, name, None) for name in _ENTITY_EVENT_HANDLER_NAMES
}


def _clone_components_and_tags(source: Entity, target: Entity) -> None:
    """Deep-copy *source*'s components and tags into *target*."""
    for comp in source.components:
        target.add_component(copy.deepcopy(comp))
    for tag in source.tags:
        target.add_tag(tag)


def _clone_entity_tree(
    target: Scene,
    originals: Iterable[Entity],
    *,
    root_parent_id: str | None,
) -> tuple[list[Entity], dict[str, str]]:
    """Clone entities with fresh IDs and remapped parents into ``target``."""
    source_entities = tuple(originals)
    id_map = {entity.entity_id: str(uuid.uuid4()) for entity in source_entities}
    clones: list[Entity] = []
    for original in source_entities:
        new_parent_id = (
            id_map.get(original.parent_id, original.parent_id)
            if original.parent_id is not None
            else root_parent_id
        )
        cloned = Entity(
            original.name,
            entity_id=id_map[original.entity_id],
            enabled=original.enabled,
            layer=original.layer,
            parent_id=new_parent_id,
        )
        _clone_components_and_tags(original, cloned)
        target.add_entity(cloned)
        clones.append(cloned)
    return clones, id_map


@dataclass(frozen=True, slots=True)
class SceneEntityOrigin:
    """Authored provenance of one scene entity (never serialized).

    ``kind`` is one of:

    - ``"authored"`` — an ordinary authored entity (persisted by compact saves).
    - ``"instance_root"`` — an authored entity carrying a Scene Instance whose
      own transform/overrides are persisted; its materialized children are not.
    - ``"materialized"`` — a descendant regenerated from a Scene Instance source,
      omitted from compact saves.
    """

    kind: str
    instance_root_id: str | None = None
    source_path: str | None = None


@dataclass(frozen=True, slots=True)
class WorldTransform2D:
    """Canonical parent-composed World-space 2D pose for a Scene Entity."""

    position: tuple[float, float]
    rotation: float
    scale: tuple[float, float]

    def __post_init__(self) -> None:
        values = (*self.position, self.rotation, *self.scale)
        if len(self.position) != 2 or len(self.scale) != 2 or not all(
            math.isfinite(float(value)) for value in values
        ):
            raise ValueError("WorldTransform2D values must be finite 2D pose values")
        object.__setattr__(self, "position", (float(self.position[0]), float(self.position[1])))
        object.__setattr__(self, "rotation", float(self.rotation))
        object.__setattr__(self, "scale", (float(self.scale[0]), float(self.scale[1])))


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
        self._component_entities: dict[type[Component], list[Entity]] = {}
        # Membership sets keep the ordered component lists off the per-entity
        # linear membership check used during large scene construction.
        self._component_entity_sets: dict[type[Component], set[Entity]] = {}
        self._component_entity_order: dict[int, int] = {}
        self._next_component_entity_order = 0
        self._pending_transform_entities: dict[str, Entity] = {}
        self._pending_removed_transform_entity_ids: set[str] = set()
        self._pending_render_entity_ids: set[str] = set()
        self._entity_event_targets: dict[str, list[Entity]] = {
            name: [] for name in _ENTITY_EVENT_HANDLER_NAMES
        }
        # Instance-root entity_id -> materialized descendant entity_ids. Purely
        # runtime bookkeeping (never serialized): lets Project.save_scene omit
        # resolve-from-source content and lets the editor mark it read-only-ish.
        self._instance_children: dict[str, set[str]] = {}
        # Materialized descendant entity_id -> owning instance-root entity_id
        # (runtime-only reverse index, never serialized). Lets entity_origin()
        # answer provenance in O(1) without scanning every instance root.
        self._instance_roots: dict[str, str] = {}
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

    def iter_entities(self) -> Iterator[Entity]:
        """Iterate entities in insertion order without a snapshot allocation.

        Callers must not add or remove entities while consuming the iterator.
        Use :attr:`entities` when a stable snapshot is required.
        """
        return iter(self._entities)

    def entity_order(self, entity: Entity) -> int:
        """Return an entity's stable insertion ordinal within this Scene."""
        try:
            return self._component_entity_order[id(entity)]
        except KeyError as exc:
            raise KeyError(f"entity is not in this Scene: {entity.entity_id!r}") from exc

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
        self._component_entity_order[id(entity)] = self._next_component_entity_order
        self._next_component_entity_order += 1
        entity._add_scene_owner(self)
        self._entity_transform_changed(entity)
        self._entity_render_changed(entity)
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
            for entity in subtree:
                self._entity_removed(entity)
                self._unindex_entity_components(entity)
                entity._remove_scene_owner(self)
                self._component_entity_order.pop(id(entity), None)
            if self._entity_index is not None:
                for removed_id in ids_to_remove:
                    self._entity_index.pop(removed_id, None)
            self._forget_instance_bookkeeping(ids_to_remove)
            self._children_index = None
            return True
        for i, entity in enumerate(self._entities):
            if entity.entity_id == entity_id:
                self._entities.pop(i)
                self._entity_removed(entity)
                self._unindex_entity_components(entity)
                entity._remove_scene_owner(self)
                self._component_entity_order.pop(id(entity), None)
                if self._entity_index is not None:
                    self._entity_index.pop(entity_id, None)
                self._forget_instance_bookkeeping({entity_id})
                self._children_index = None
                return True
        return False

    def transfer_entities_to(
        self,
        target: Scene,
        entity_ids: tuple[str, ...] | None = None,
    ) -> tuple[Entity, ...]:
        """Move a complete set of Entity objects to another Scene without cloning.

        The transfer preserves Entity identity and SceneInstance bookkeeping.
        Selected parent/child subtrees and any materialized SceneInstance subtree
        must move as a whole so neither Scene publishes dangling ownership.
        """
        if not isinstance(target, Scene) or target is self:
            raise ValueError("target must be a different Scene")
        source_index = self._ensure_entity_index()
        selected_ids = set(source_index) if entity_ids is None else set(entity_ids)
        if not selected_ids:
            return ()
        missing = selected_ids - source_index.keys()
        if missing:
            raise KeyError(f"cannot transfer missing Entity IDs: {sorted(missing)!r}")
        target_index = target._ensure_entity_index()
        duplicates = selected_ids & target_index.keys()
        if duplicates:
            raise ValueError(f"target Scene already contains Entity IDs: {sorted(duplicates)!r}")
        for entity_id in selected_ids:
            entity = source_index[entity_id]
            if entity.parent_id in source_index and entity.parent_id not in selected_ids:
                raise ValueError("Entity transfer cannot leave a parent in another Scene")
            if any(
                child.entity_id not in selected_ids
                for child in self.children_of(entity_id)
            ):
                raise ValueError("Entity transfer cannot leave children in another Scene")
        moved_instance_roots: dict[str, set[str]] = {}
        for root_id, children in self._instance_children.items():
            affected = root_id in selected_ids or bool(children & selected_ids)
            if not affected:
                continue
            subtree = {root_id, *children}
            if not subtree <= selected_ids:
                raise ValueError("Scene Instance materialized content must transfer as a whole")
            moved_instance_roots[root_id] = set(children)

        moved = tuple(entity for entity in self._entities if entity.entity_id in selected_ids)
        self._entities = [entity for entity in self._entities if entity.entity_id not in selected_ids]
        for entity in moved:
            self._entity_removed(entity)
            self._unindex_entity_components(entity)
            entity._remove_scene_owner(self)
            self._component_entity_order.pop(id(entity), None)
            target._entities.append(entity)
            target_index[entity.entity_id] = entity
            target._component_entity_order[id(entity)] = target._next_component_entity_order
            target._next_component_entity_order += 1
            entity._add_scene_owner(target)
            target._entity_transform_changed(entity)
            if target._children_index is not None:
                target._children_index.setdefault(entity.parent_id, []).append(entity)
        for root_id, children in moved_instance_roots.items():
            for child_id in children:
                self._instance_roots.pop(child_id, None)
                target._instance_roots[child_id] = root_id
            del self._instance_children[root_id]
        target._instance_children.update(moved_instance_roots)
        self._entity_index = None
        self._children_index = None
        return moved

    def _forget_instance_bookkeeping(self, removed_ids: set[str]) -> None:
        """Drop any scene-instance tracking that referenced a removed entity."""
        for root_id in removed_ids:
            children = self._instance_children.pop(root_id, None)
            if children is not None:
                for child_id in children:
                    self._instance_roots.pop(child_id, None)
        for children in self._instance_children.values():
            for child_id in children & removed_ids:
                self._instance_roots.pop(child_id, None)
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
        _clones, id_map = _clone_entity_tree(self, subtree, root_parent_id=None)
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
        """Return an entity's parent-composed World position and rotation.

        Missing or disabled transforms use the identity pose, matching render
        extraction. Missing parents are treated as roots; malformed cycles are
        rejected rather than recursing indefinitely. Use ``world_transform``
        when scale is also required.
        """
        pose = self.world_transform(entity_id)
        return pose.position[0], pose.position[1], pose.rotation

    def world_transform(self, entity_id: str) -> WorldTransform2D:
        """Resolve local Transform and all parents to the canonical World pose."""
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

        x, y, rotation, scale_x, scale_y = resolve(entity_id)
        return WorldTransform2D((x, y), rotation, (scale_x, scale_y))

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
        return entity_id in self._instance_roots

    def entity_origin(self, entity_id: str) -> SceneEntityOrigin:
        """Return the authored provenance of ``entity_id``.

        Distinguishes ordinary authored entities, authored Scene Instance roots
        (whose transform and overrides are persisted), and materialized
        descendants (omitted from compact saves and regenerated from their
        source on load).
        """
        entity = self.find_entity(entity_id)
        if entity is None:
            raise KeyError(f"entity not found: {entity_id!r}")
        root_id = self._instance_roots.get(entity_id)
        if root_id is not None:
            root = self.find_entity(root_id)
            source_path: str | None = None
            if root is not None:
                from expra_engine.core.scene.scene_instance import SceneInstanceComponent

                component = root.get_component(SceneInstanceComponent)
                source_path = component.source_path if component is not None else None
            return SceneEntityOrigin("materialized", root_id, source_path)
        from expra_engine.core.scene.scene_instance import SceneInstanceComponent

        if entity.get_component(SceneInstanceComponent) is not None:
            return SceneEntityOrigin("instance_root", None, None)
        return SceneEntityOrigin("authored", None, None)

    def _set_instance_children(self, root_id: str, entity_ids: set[str]) -> None:
        """Record which entity ids were materialized under instance root ``root_id``."""
        previous = self._instance_children.get(root_id)
        if previous is not None:
            for child_id in previous:
                self._instance_roots.pop(child_id, None)
        self._instance_children[root_id] = set(entity_ids)
        for child_id in entity_ids:
            self._instance_roots[child_id] = root_id

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
        """Breadth-first traversal of the entity hierarchy.

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
        seen: set[str] = set()
        while cursor < len(queue):
            entity = queue[cursor]
            cursor += 1
            if entity.entity_id in seen:
                continue
            seen.add(entity.entity_id)
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
        return tuple(self.iter_entities_by_component(cls))

    def iter_entities_by_component(self, cls: type) -> Iterator[Entity]:
        """Iterate matching entities in scene order without a result snapshot."""
        return iter(self._component_entities.get(cls, ()))

    def _entities_for_event(self, handler_name: str) -> tuple[Entity, ...]:
        if getattr(Entity, handler_name, None) is not _BASE_ENTITY_EVENT_HANDLERS.get(handler_name):
            return self.entities
        return tuple(self._entity_event_targets.get(handler_name, ()))

    def _refresh_entity_event_targets(self, entity: Entity) -> None:
        order = self._component_entity_order.get(id(entity))
        if order is None:
            return
        for handler_name in _ENTITY_EVENT_HANDLER_NAMES:
            class_handler = getattr(type(entity), handler_name, None)
            custom_handler = (
                class_handler is not _BASE_ENTITY_EVENT_HANDLERS[handler_name]
                or handler_name in entity.__dict__
            )
            should_dispatch = bool(entity._behaviours) or custom_handler
            bucket = self._entity_event_targets[handler_name]
            present = entity in bucket
            if should_dispatch == present:
                continue
            if should_dispatch:
                insert_at = next(
                    (
                        index
                        for index, existing in enumerate(bucket)
                        if self._component_entity_order[id(existing)] > order
                    ),
                    len(bucket),
                )
                bucket.insert(insert_at, entity)
            else:
                bucket.remove(entity)

    def _remove_entity_event_targets(self, entity: Entity) -> None:
        for bucket in self._entity_event_targets.values():
            try:
                bucket.remove(entity)
            except ValueError:
                continue

    def _entity_component_added(self, entity: Entity, component: Component) -> None:
        self._entity_render_changed(entity)
        if isinstance(component, TransformComponent):
            self._entity_transform_changed(entity)
        for component_type in type(component).__mro__:
            if not isinstance(component_type, type) or not issubclass(component_type, Component):
                continue
            self._insert_component_entity(entity, component_type)

    def _insert_component_entity(
        self, entity: Entity, component_type: type[Component]
    ) -> None:
        members = self._component_entity_sets.setdefault(component_type, set())
        if entity in members:
            return
        order = self._component_entity_order[id(entity)]
        bucket = self._component_entities.setdefault(component_type, [])
        if not bucket or order > self._component_entity_order[id(bucket[-1])]:
            bucket.append(entity)
        else:
            insert_at = next(
                index
                for index, existing in enumerate(bucket)
                if self._component_entity_order[id(existing)] > order
            )
            bucket.insert(insert_at, entity)
        members.add(entity)

    def _entity_component_removed(self, entity: Entity, component: Component) -> None:
        self._entity_render_changed(entity)
        if isinstance(component, TransformComponent):
            self._entity_transform_changed(entity)
        for component_type in type(component).__mro__:
            if not isinstance(component_type, type) or not issubclass(component_type, Component):
                continue
            if entity.get_component(component_type) is not None:
                continue
            bucket = self._component_entities.get(component_type)
            if bucket is None:
                continue
            self._remove_component_entity(entity, component_type)

    def _remove_component_entity(
        self, entity: Entity, component_type: type[Component]
    ) -> None:
        bucket = self._component_entities.get(component_type)
        members = self._component_entity_sets.get(component_type)
        if bucket is None or members is None or entity not in members:
            return
        index = next(index for index, existing in enumerate(bucket) if existing is entity)
        bucket.pop(index)
        members.remove(entity)
        if not bucket:
            del self._component_entities[component_type]
            del self._component_entity_sets[component_type]

    def _entity_transform_changed(self, entity: Entity) -> None:
        if id(entity) in self._component_entity_order:
            self._pending_removed_transform_entity_ids.discard(entity.entity_id)
            self._pending_transform_entities[entity.entity_id] = entity
            self._entity_render_changed(entity)
            children_index = self._ensure_children_index()
            descendants = children_index.get(entity.entity_id)
            if not descendants:
                return
            queue = list(descendants)
            seen = {entity.entity_id}
            cursor = 0
            while cursor < len(queue):
                descendant = queue[cursor]
                cursor += 1
                if descendant.entity_id in seen:
                    continue
                seen.add(descendant.entity_id)
                descendant._bump_physics_revision()
                queue.extend(children_index.get(descendant.entity_id, ()))

    def _entity_component_changed(self, entity: Entity, component: Component) -> None:
        self._entity_render_changed(entity)
        if isinstance(component, TransformComponent):
            self._entity_transform_changed(entity)

    def _entity_render_changed(self, entity: Entity) -> None:
        if id(entity) in self._component_entity_order:
            self._pending_render_entity_ids.add(entity.entity_id)

    def _take_render_entity_ids(self) -> tuple[str, ...]:
        changed = tuple(self._pending_render_entity_ids)
        self._pending_render_entity_ids.clear()
        return changed

    def _mark_all_transform_entities_dirty(self) -> None:
        self._pending_transform_entities.update(
            (entity.entity_id, entity) for entity in self._entities
        )

    def _entity_removed(self, entity: Entity) -> None:
        self._pending_transform_entities.pop(entity.entity_id, None)
        self._pending_removed_transform_entity_ids.add(entity.entity_id)
        self._pending_render_entity_ids.add(entity.entity_id)

    def _take_transform_changes(self) -> tuple[tuple[Entity, ...], tuple[str, ...]]:
        changed = tuple(self._pending_transform_entities.values())
        removed = tuple(self._pending_removed_transform_entity_ids)
        self._pending_transform_entities.clear()
        self._pending_removed_transform_entity_ids.clear()
        return changed, removed

    def _take_removed_transform_entity_ids(self) -> tuple[str, ...]:
        removed = tuple(self._pending_removed_transform_entity_ids)
        self._pending_removed_transform_entity_ids.clear()
        return removed

    def _unindex_entity_components(self, entity: Entity) -> None:
        component_types = {
            component_type
            for component in entity.components
            for component_type in type(component).__mro__
            if isinstance(component_type, type) and issubclass(component_type, Component)
        }
        for component_type in component_types:
            self._remove_component_entity(entity, component_type)

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
