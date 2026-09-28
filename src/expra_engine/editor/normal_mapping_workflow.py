"""Plan and apply undoable normal-map authoring operations for an open document."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import (
    AddComponentCommand,
    Command,
    CompositeCommand,
    SetComponentPropertyCommand,
)
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.normal_mapping import (
    NormalMapMode,
    NormalMapResolver,
    normal_texture_sources,
)
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent

__all__ = (
    "AutoMapFinding",
    "AutoMapPlan",
    "AutoMapState",
    "apply_level_auto_map",
    "build_level_auto_map_plan",
)


class AutoMapState(StrEnum):
    RESOLVED = "resolved"
    MISSING = "missing"
    INVALID = "invalid"
    ALREADY_CONFIGURED = "already_configured"
    PRESERVED = "preserved"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class AutoMapFinding:
    entity_id: str
    entity_name: str
    visual_name: str
    base_texture_id: str | None
    normal_texture_id: str | None
    state: AutoMapState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _AutoMapAssignment:
    entity_id: str
    add_material: bool


@dataclass(frozen=True, slots=True)
class AutoMapPlan:
    """Immutable preview result; applying it rechecks its document and targets."""

    scene: Scene
    findings: tuple[AutoMapFinding, ...]
    _assignments: tuple[_AutoMapAssignment, ...]

    @property
    def assign_entity_ids(self) -> tuple[str, ...]:
        return tuple(item.entity_id for item in self._assignments)

    @property
    def can_apply(self) -> bool:
        return bool(self._assignments)


def build_level_auto_map_plan(scene: Scene, resources: Any) -> AutoMapPlan:
    """Inspect supported visual resources without mutating the authored Scene."""
    resolver = NormalMapResolver(resources)
    findings: list[AutoMapFinding] = []
    assignments: list[_AutoMapAssignment] = []
    for entity in scene.entities:
        visuals = normal_texture_sources(entity)
        if not visuals:
            if any(isinstance(item, (PrimitiveComponent, TextComponent)) for item in entity.components):
                findings.append(
                    AutoMapFinding(
                        entity.entity_id,
                        entity.name,
                        "visual",
                        None,
                        None,
                        AutoMapState.UNSUPPORTED,
                        "normal maps require a textured Sprite or AnimatedSprite2D visual",
                    )
                )
            continue

        material = entity.get_component(MaterialComponent)
        if material is not None and (
            not material.enabled
            or material.normal_map_mode == NormalMapMode.EXPLICIT.value
            or (
                material.normal_map_mode == NormalMapMode.DISABLED.value
                and material.normal_texture_id is not None
            )
        ):
            reason = (
                "material is disabled"
                if not material.enabled
                else "existing explicit normal-map settings are preserved"
            )
            findings.extend(
                AutoMapFinding(
                    entity.entity_id,
                    entity.name,
                    visual_name,
                    texture_id,
                    material.normal_texture_id,
                    AutoMapState.PRESERVED,
                    reason,
                )
                for visual_name, texture_id in visuals
            )
            continue

        if material is not None and material.normal_map_mode == NormalMapMode.AUTO_PAIR.value:
            findings.extend(
                _finding(resolver, entity, visual_name, texture_id, AutoMapState.ALREADY_CONFIGURED)
                for visual_name, texture_id in visuals
            )
            continue

        entity_resolved = False
        for visual_name, texture_id in visuals:
            resolution = resolver.inspect(texture_id, NormalMapMode.AUTO_PAIR)
            state = {
                "resolved": AutoMapState.RESOLVED,
                "missing": AutoMapState.MISSING,
                "invalid": AutoMapState.INVALID,
            }.get(resolution.status.value, AutoMapState.INVALID)
            findings.append(
                AutoMapFinding(
                    entity.entity_id,
                    entity.name,
                    visual_name,
                    texture_id,
                    resolution.normal_texture_id,
                    state,
                    resolution.detail,
                )
            )
            entity_resolved = entity_resolved or state is AutoMapState.RESOLVED
        if entity_resolved:
            assignments.append(
                _AutoMapAssignment(entity.entity_id, add_material=material is None)
            )

    return AutoMapPlan(scene, tuple(findings), tuple(assignments))


def apply_level_auto_map(window: Any, plan: AutoMapPlan) -> bool:
    """Apply the reviewed plan as one undo entry; reject stale document targets."""
    active_document = getattr(window, "_active_document", None)
    if active_document is None or active_document.document is not plan.scene:
        raise ValueError("normal-map plan is no longer active for the current document")
    commands: list[Command] = []
    for assignment in plan._assignments:
        entity = plan.scene.find_entity(assignment.entity_id)
        if entity is None:
            raise ValueError("normal-map plan contains an entity that no longer exists")
        material = entity.get_component(MaterialComponent)
        if assignment.add_material:
            if material is not None:
                if material.normal_map_mode == NormalMapMode.AUTO_PAIR.value:
                    continue
                raise ValueError("normal-map plan is stale: target Entity gained a MaterialComponent")
            commands.append(
                AddComponentCommand(
                    plan.scene,
                    entity.entity_id,
                    MaterialComponent,
                    MaterialComponent(normal_map_mode=NormalMapMode.AUTO_PAIR),
                )
            )
        else:
            if material is not None and material.normal_map_mode == NormalMapMode.AUTO_PAIR.value:
                continue
            if (
                material is None
                or not material.enabled
                or material.normal_map_mode != NormalMapMode.DISABLED.value
                or material.normal_texture_id is not None
            ):
                raise ValueError("normal-map plan is stale: target Material settings changed")
            commands.append(
                SetComponentPropertyCommand(
                    plan.scene,
                    entity.entity_id,
                    MaterialComponent,
                    "normal_map_mode",
                    NormalMapMode.AUTO_PAIR.value,
                )
            )
    if not commands:
        return False
    command = commands[0] if len(commands) == 1 else CompositeCommand(
        commands, f"Auto-map normal textures for {len(commands)} entities"
    )
    active_document.command_stack.push(command)
    window._update_undo_redo_state()
    window._present_all()
    return True


def _finding(
    resolver: NormalMapResolver,
    entity: Entity,
    visual_name: str,
    texture_id: str,
    state: AutoMapState,
) -> AutoMapFinding:
    resolution = resolver.inspect(texture_id, NormalMapMode.AUTO_PAIR)
    return AutoMapFinding(
        entity.entity_id,
        entity.name,
        visual_name,
        texture_id,
        resolution.normal_texture_id,
        state,
        resolution.detail,
    )
