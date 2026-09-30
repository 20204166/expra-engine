"""Toolkit-independent hierarchy row projection for the hierarchy panel.

Flattens a Scene/Level or a World into ``(row_id, parent_id, text, tags)`` rows
that the hierarchy panel reconciles into its tree widget.
"""

from __future__ import annotations

from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.core.world import World
from expra_engine.ui.styles import EDITOR_ENTITY_MARKERS, editor_entity_kind

HierarchyRow = tuple[str, str, str, tuple[str, ...]]


def collect_world_rows(world: World) -> list[HierarchyRow]:
    """Project only authored World descriptors and connections into rows."""
    rows = [
        ("world:root", "", world.name, ()),
        ("world:levels", "world:root", "Levels", ()),
    ]
    for descriptor in world.levels:
        suffix = " [Initial]" if descriptor.instance_id == world.initial_level_id else ""
        rows.append(
            (
                f"level:{descriptor.instance_id}",
                "world:levels",
                f"{descriptor.instance_id} — {descriptor.resource_path}{suffix}",
                (),
            )
        )
    rows.append(("world:connections", "world:root", "Connections", ()))
    level_names = {item.instance_id: item.instance_id for item in world.levels}
    for connection in world.connections:
        label = (
            f"{level_names[connection.source_level_id]}.{connection.source_anchor_id} "
            f"→ {level_names[connection.destination_level_id]}."
            f"{connection.destination_anchor_id} [{connection.transition.value}]"
        )
        rows.append(
            (f"connection:{connection.connection_id}", "world:connections", label, ())
        )
    return rows


def collect_entity_rows(scene: Scene | None) -> list[HierarchyRow]:
    """Flatten a scene in stable preorder without recursion depth limits."""
    if scene is None:
        return []
    incoming: list[HierarchyRow] = []
    stack = [(entity, "") for entity in reversed(scene.roots())]
    while stack:
        entity, parent = stack.pop()
        state = "disabled" if not entity.enabled else ""
        kind = editor_entity_kind(entity.name)
        label = (
            f"[{EDITOR_ENTITY_MARKERS[kind]}] {entity.name}"
            if kind is not None
            else entity.name
        )
        if entity.get_component(SceneInstanceComponent) is not None:
            label = f"[INST] {label}"
        elif scene.is_instance_materialized(entity.entity_id):
            label = f"[in] {label}"
        incoming.append((entity.entity_id, parent, label, (state,) if state else ()))
        children = scene.children_of(entity.entity_id)
        stack.extend((child, entity.entity_id) for child in reversed(children))
    return incoming
