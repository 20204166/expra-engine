"""Plan and apply undoable normal-map authoring operations for an open document.

V3 model: planning is deduplicated by *base texture*, not one row per
Entity/frame. Each unique base texture becomes one ``NormalMapAssetCandidate``
carrying structured usage records and a classification. Applying the reviewed
plan writes material assignments as a single undoable command; generation of
missing normal-map PNGs lives in ``editor/normal_map_generation.py`` and is
never part of the plan builder.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from expra_engine.core.scene import Scene
from expra_engine.editor.commands import (
    AddComponentCommand,
    CompositeCommand,
    SetComponentPropertyCommand,
)
from expra_engine.editor.normal_map_generation import normal_map_output_id
from expra_engine.runtime.animated_sprite_2d import AnimatedSprite2DComponent
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.normal_mapping import (
    NormalMapMode,
    NormalMapResolutionStatus,
    NormalMapResolver,
)
from expra_engine.runtime.visual_components import SpriteComponent

__all__ = (
    "NormalMapAssetCandidate",
    "NormalMapClassification",
    "NormalMapInstanceSource",
    "NormalMapSetupPlan",
    "NormalMapUsage",
    "apply_normal_map_setup",
    "build_normal_map_setup_plan",
)

_GENERATABLE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga"})


class NormalMapClassification(StrEnum):
    READY_EXISTING = "ready_existing"
    CAN_GENERATE = "can_generate"
    MISSING_MANUAL = "missing_manual"
    ALREADY_CONFIGURED = "already_configured"
    PRESERVED = "preserved"
    INVALID = "invalid"
    EXTERNAL_INSTANCE = "external_instance"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class NormalMapUsage:
    """One visual reference to a base texture, with enough context to author it."""

    entity_id: str
    entity_name: str
    base_texture_id: str
    visual_kind: str  # "Sprite" or "Animation"
    animation_name: str | None = None
    frame_index: int | None = None
    region: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class NormalMapAssetCandidate:
    """One unique base texture and everything that references it."""

    base_texture_id: str
    usages: tuple[NormalMapUsage, ...]
    existing_normal_id: str | None
    classification: NormalMapClassification
    generation_eligible: bool
    detail: str | None = None

    @property
    def used_by(self) -> int:
        return len(self.usages)


@dataclass(frozen=True, slots=True)
class NormalMapInstanceSource:
    """Aggregate of an authored Scene Instance's source-scene dependencies."""

    source_path: str
    root_id: str
    root_name: str
    visual_count: int


@dataclass(frozen=True, slots=True)
class NormalMapSetupPlan:
    """Immutable preview result; applying it rechecks its document and targets."""

    scene: Scene
    candidates: tuple[NormalMapAssetCandidate, ...]
    instance_sources: tuple[NormalMapInstanceSource, ...]
    not_applicable_count: int

    def candidates_by_id(self) -> dict[str, NormalMapAssetCandidate]:
        return {candidate.base_texture_id: candidate for candidate in self.candidates}

    @property
    def ready_count(self) -> int:
        return sum(c.classification is NormalMapClassification.READY_EXISTING for c in self.candidates)

    @property
    def generatable_count(self) -> int:
        return sum(c.classification is NormalMapClassification.CAN_GENERATE for c in self.candidates)

    @property
    def unresolved_count(self) -> int:
        return sum(c.classification is NormalMapClassification.MISSING_MANUAL for c in self.candidates)


def _region_tuple(region: Any) -> tuple[int, int, int, int] | None:
    if region is None:
        return None
    return (region.x, region.y, region.width, region.height)


def _collect_usages(entity: Any) -> tuple[NormalMapUsage, ...]:
    usages: list[NormalMapUsage] = []
    for component in entity.components:
        if isinstance(component, SpriteComponent):
            if component.asset:
                usages.append(
                    NormalMapUsage(
                        entity_id=entity.entity_id,
                        entity_name=entity.name,
                        base_texture_id=component.asset,
                        visual_kind="Sprite",
                        region=_region_tuple(component.region),
                    )
                )
        elif isinstance(component, AnimatedSprite2DComponent):
            for animation_name in component.frames.names:
                animation = component.frames.get(animation_name)
                for index, frame in enumerate(animation.frames):
                    usages.append(
                        NormalMapUsage(
                            entity_id=entity.entity_id,
                            entity_name=entity.name,
                            base_texture_id=frame.asset_id,
                            visual_kind="Animation",
                            animation_name=animation_name,
                            frame_index=index,
                            region=_region_tuple(frame.region),
                        )
                    )
    return tuple(usages)


def _material_state(entity: Any) -> str:
    material = entity.get_component(MaterialComponent)
    if material is None:
        return "unconfigured"
    if not material.enabled:
        return "disabled"
    if material.normal_map_mode == NormalMapMode.EXPLICIT.value:
        return "explicit"
    if material.normal_map_mode == NormalMapMode.AUTO_PAIR.value:
        return "auto_pair"
    if material.normal_texture_id is not None:
        return "explicit"
    return "unconfigured"


def _base_exists(resources: Any, base_texture_id: str) -> bool:
    try:
        resources.metadata(base_texture_id)
    except (OSError, ValueError):
        return False
    return True


def _generation_eligible(base_texture_id: str) -> bool:
    try:
        normal_map_output_id(base_texture_id)
    except ValueError:
        return False
    return True


def _classify(
    resolution_status: str,
    *,
    base_exists: bool,
    eligible: bool,
) -> NormalMapClassification:
    if resolution_status == NormalMapResolutionStatus.RESOLVED.value:
        return NormalMapClassification.READY_EXISTING
    if resolution_status == NormalMapResolutionStatus.INVALID.value:
        return NormalMapClassification.INVALID
    # MISSING
    if not base_exists or not eligible:
        return NormalMapClassification.MISSING_MANUAL
    return NormalMapClassification.CAN_GENERATE


def build_normal_map_setup_plan(scene: Scene, resources: Any) -> NormalMapSetupPlan:
    """Inspect the authored document without mutating it.

    Materialized Scene-instance children are aggregated under their source
    scene (``instance_sources``) and never surfaced as actionable candidates;
    primitive/text entities only advance ``not_applicable_count``.
    """
    resolver = NormalMapResolver(resources)
    usages_by_base: dict[str, list[NormalMapUsage]] = {}
    instance_sources: dict[str, dict[str, Any]] = {}
    not_applicable = 0

    for entity in scene.entities:
        if scene.is_instance_materialized(entity.entity_id):
            usages = _collect_usages(entity)
            if not usages:
                continue
            origin = scene.entity_origin(entity.entity_id)
            source_path = origin.source_path or origin.instance_root_id or "<unknown>"
            group = instance_sources.setdefault(
                source_path,
                {"root_id": origin.instance_root_id, "root_name": "", "visual_count": 0},
            )
            group["visual_count"] += len(usages)
            if group["root_name"] == "" and origin.instance_root_id is not None:
                root = scene.find_entity(origin.instance_root_id)
                group["root_name"] = root.name if root is not None else ""
            continue

        usages = _collect_usages(entity)
        if not usages:
            not_applicable += 1
            continue
        for usage in usages:
            usages_by_base.setdefault(usage.base_texture_id, []).append(usage)

    candidates: list[NormalMapAssetCandidate] = []
    for base_texture_id, usages in usages_by_base.items():
        states = {_material_state(scene.find_entity(u.entity_id)) for u in usages}
        resolution = resolver.inspect(base_texture_id, NormalMapMode.AUTO_PAIR)
        if "disabled" in states or "explicit" in states:
            classification = NormalMapClassification.PRESERVED
            generation_eligible = False
        elif states == {"auto_pair"}:
            classification = NormalMapClassification.ALREADY_CONFIGURED
            generation_eligible = False
        else:
            generation_eligible = _generation_eligible(base_texture_id)
            classification = _classify(
                resolution.status.value,
                base_exists=_base_exists(resources, base_texture_id),
                eligible=generation_eligible,
            )
        candidates.append(
            NormalMapAssetCandidate(
                base_texture_id=base_texture_id,
                usages=tuple(usages),
                existing_normal_id=resolution.normal_texture_id
                if resolution.status is NormalMapResolutionStatus.RESOLVED
                else None,
                classification=classification,
                generation_eligible=generation_eligible,
                detail=resolution.detail,
            )
        )

    sources = tuple(
        NormalMapInstanceSource(
            source_path=source_path,
            root_id=group["root_id"],
            root_name=group["root_name"],
            visual_count=group["visual_count"],
        )
        for source_path, group in sorted(instance_sources.items())
    )
    return NormalMapSetupPlan(
        scene,
        tuple(candidates),
        sources,
        not_applicable_count=not_applicable,
    )


def apply_normal_map_setup(
    window: Any,
    plan: NormalMapSetupPlan,
    base_texture_ids: Iterable[str],
) -> bool:
    """Apply auto-pair material assignments for selected base textures, as one undo entry.

    Only *unconfigured* materials are touched; disabled/explicit/auto-pair
    materials are preserved. The plan is revalidated against the active
    document before any command runs.
    """
    active_document = getattr(window, "_active_document", None)
    if active_document is None or active_document.document is not plan.scene:
        raise ValueError("normal-map plan is no longer active for the current document")

    selected = set(base_texture_ids)
    candidates_by_id = plan.candidates_by_id()
    commands: list[Any] = []
    for base_texture_id in selected:
        candidate = candidates_by_id.get(base_texture_id)
        if candidate is None:
            raise ValueError("normal-map plan contains an unknown base texture selection")
        for entity_id in dict.fromkeys(u.entity_id for u in candidate.usages):
            entity = plan.scene.find_entity(entity_id)
            if entity is None:
                raise ValueError("normal-map plan contains an entity that no longer exists")
            material = entity.get_component(MaterialComponent)
            if material is None:
                commands.append(
                    AddComponentCommand(
                        plan.scene,
                        entity_id,
                        MaterialComponent,
                        MaterialComponent(normal_map_mode=NormalMapMode.AUTO_PAIR),
                    )
                )
            elif (
                material.enabled
                and material.normal_map_mode == NormalMapMode.DISABLED.value
                and material.normal_texture_id is None
            ):
                commands.append(
                    SetComponentPropertyCommand(
                        plan.scene,
                        entity_id,
                        MaterialComponent,
                        "normal_map_mode",
                        NormalMapMode.AUTO_PAIR.value,
                    )
                )

    if not commands:
        return False
    command = commands[0] if len(commands) == 1 else CompositeCommand(
        commands, f"Pair normal maps for {len(commands)} entities"
    )
    active_document.command_stack.push(command)
    window._update_undo_redo_state()
    window._present_all()
    return True
