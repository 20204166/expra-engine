"""Reusable Scene composition: SceneInstanceComponent and its resolver.

A Scene Instance is an ordinary Entity carrying a SceneInstanceComponent.
Resolving it materializes a deep copy of the referenced source Scene's
hierarchy as fresh child entities under that root, so the instance root's
own (already existing) TransformComponent is the root-transform override --
no separate transform mechanism is needed.

Materialized descendants are resolve-from-source content: Scene tracks them
(``Scene.is_instance_materialized``) so ``Project.save_scene`` can omit them
from the persisted file, and they are regenerated fresh on every load. This
is the instancing/duplicating distinction the spec requires: instancing
keeps source identity via re-resolution; ``Scene.clone_entity`` (unrelated
to this module) makes an independent copy with no source link.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from expra_engine.core.component import Component
from expra_engine.core.entity import Entity

if TYPE_CHECKING:
    from expra_engine.core.scene.scene import Scene

__all__ = (
    "SceneInstanceComponent",
    "SceneInstanceCycleError",
    "SceneInstanceSourceError",
    "resolve_scene_instances",
)


class SceneInstanceSourceError(ValueError):
    """Raised when a scene instance's source scene cannot be resolved."""

    def __init__(self, entity_name: str, source_path: str, reason: Exception) -> None:
        super().__init__(
            f"scene instance {entity_name!r} could not resolve source {source_path!r}: {reason}"
        )
        self.entity_name = entity_name
        self.source_path = source_path


class SceneInstanceCycleError(ValueError):
    """Raised when resolving a scene instance would revisit a scene already in progress."""

    def __init__(self, entity_name: str, source_path: str, chain: frozenset[str]) -> None:
        ordered = ", ".join(sorted(chain))
        super().__init__(
            f"scene instance {entity_name!r} source {source_path!r} would create a cycle "
            f"(already resolving: {ordered})"
        )
        self.entity_name = entity_name
        self.source_path = source_path


@dataclass
class SceneInstanceComponent(Component):
    """Reference to a reusable source Scene, materialized as child entities.

    ``source_path`` is a project-relative scene path (same convention as
    ``Project.scene_paths()``/``start_scene``: ``"scenes/foo.json"``).
    ``overrides`` maps a materialized descendant's entity ``name`` to a dict
    of ``ScriptComponent.exposed_values`` keys/values applied after each
    resolve. Phase 1 scope only -- no deeper override inheritance.
    """

    component_type: str = field(default="scene_instance", init=False, repr=False)

    source_path: str = ""
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __init__(
        self,
        source_path: str,
        *,
        overrides: dict[str, dict[str, Any]] | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        if not source_path:
            raise ValueError("scene instance source_path cannot be empty")
        self.source_path = source_path
        self.overrides = {key: dict(value) for key, value in (overrides or {}).items()}
        try:
            json.dumps(self.overrides)
        except (TypeError, ValueError) as exc:
            raise ValueError("scene instance overrides must be JSON-serializable") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "source_path": self.source_path,
            "overrides": {key: dict(value) for key, value in self.overrides.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SceneInstanceComponent:
        return cls(
            str(data["source_path"]),
            overrides={
                str(key): dict(value) for key, value in dict(data.get("overrides", {})).items()
            },
            enabled=bool(data.get("enabled", True)),
        )


def resolve_scene_instances(
    scene: Scene,
    resolve_source: Callable[[str], Scene],
    *,
    chain: frozenset[str] = frozenset(),
) -> None:
    """Materialize every ``SceneInstanceComponent`` in ``scene``, in place.

    ``resolve_source(source_path)`` must return an already-fully-resolved
    Scene (i.e. the caller is responsible for recursing for nested
    instances -- see ``Project.load_scene``, which threads ``chain`` through
    its own recursive calls). Safe to call more than once on the same
    ``scene``: each instance root's previously-materialized descendants are
    removed before re-materializing, so nothing duplicates.
    """
    from expra_engine.runtime.script_component import ScriptComponent

    for entity in tuple(scene.entities):
        component = entity.get_component(SceneInstanceComponent)
        if component is None:
            continue

        scene._clear_instance_subtree(entity.entity_id)

        if component.source_path in chain:
            raise SceneInstanceCycleError(entity.name, component.source_path, chain)

        try:
            source_scene = resolve_source(component.source_path)
        except SceneInstanceCycleError:
            raise
        except Exception as exc:
            raise SceneInstanceSourceError(entity.name, component.source_path, exc) from exc

        cloned = _materialize_source_scene(scene, source_scene, entity.entity_id)
        scene._set_instance_children(entity.entity_id, {clone.entity_id for clone in cloned})

        if component.overrides:
            _apply_overrides(cloned, component.overrides, ScriptComponent)


def _materialize_source_scene(
    scene: Scene, source_scene: Scene, instance_root_id: str
) -> list[Entity]:
    """Deep-copy every entity in ``source_scene`` into ``scene`` under a fresh root parent.

    Mirrors ``Scene.clone_entity(recursive=True)``'s remap algorithm, except
    the source entities come from a different Scene and the source's own
    root-level entities (``parent_id is None``) are reparented under
    ``instance_root_id`` instead of staying rootless.
    """
    from expra_engine.core.scene.scene import _clone_components_and_tags

    subtree = source_scene.walk_hierarchy()
    id_map: dict[str, str] = {original.entity_id: str(uuid.uuid4()) for original in subtree}

    cloned_entities: list[Entity] = []
    for original in subtree:
        new_id = id_map[original.entity_id]
        new_parent_id = (
            instance_root_id
            if original.parent_id is None
            else id_map.get(original.parent_id, original.parent_id)
        )
        cloned = Entity(
            original.name,
            entity_id=new_id,
            enabled=original.enabled,
            layer=original.layer,
            parent_id=new_parent_id,
        )
        _clone_components_and_tags(original, cloned)
        scene.add_entity(cloned)
        cloned_entities.append(cloned)
    return cloned_entities


def _apply_overrides(
    cloned: list[Entity], overrides: dict[str, dict[str, Any]], script_component_cls: type
) -> None:
    """Apply exposed-value overrides to the first matching materialized entity by name."""
    by_name: dict[str, Entity] = {}
    for entity in cloned:
        by_name.setdefault(entity.name, entity)
    for entity_name, values in overrides.items():
        target = by_name.get(entity_name)
        if target is None:
            continue
        script = target.get_component(script_component_cls)
        if script is None:
            continue
        script.exposed_values.update(values)
