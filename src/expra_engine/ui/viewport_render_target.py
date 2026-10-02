"""Renderer-neutral render target construction for the editor viewport."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.core.spatial_index import SpatialIndex2D
from expra_engine.observability import ObservabilityWatcher, observe_stage
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.area import AreaComponent
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderItem,
    Viewport,
    _world_query_bounds,
)
from expra_engine.runtime.screen_texture import RenderEffect

__all__ = (
    "ColliderOutline",
    "EditorRenderTarget",
    "build_editor_render_target",
    "reproject_editor_render_target",
)


@dataclass(frozen=True)
class ColliderOutline:
    entity_id: str
    outline: dict[str, Any]
    position: tuple[float, float]
    is_area: bool = False

    @property
    def world_bounds(self) -> tuple[float, float, float, float]:
        if self.outline["shape"] == "circle":
            radius = float(self.outline["radius"])
            return (
                self.position[0] - radius,
                self.position[1] - radius,
                self.position[0] + radius,
                self.position[1] + radius,
            )
        half_width = float(self.outline["width"]) / 2.0
        half_height = float(self.outline["height"]) / 2.0
        return (
            self.position[0] - half_width,
            self.position[1] - half_height,
            self.position[0] + half_width,
            self.position[1] + half_height,
        )


@dataclass(frozen=True)
class EditorRenderTarget:
    """Renderer-neutral preview data plus editor-only overlay inputs."""

    frame: RenderFrame
    items: tuple[RenderItem, ...]
    selected_id: str | None
    colliders: tuple[ColliderOutline, ...] = ()
    unsupported_effects: tuple[str, ...] = ()
    render_context: RenderContext | None = None
    collider_spatial_index: SpatialIndex2D[int] | None = field(
        default=None, repr=False, compare=False
    )
    collider_ordinals_by_id: dict[str, int] = field(
        default_factory=dict, repr=False, compare=False
    )

    def visible_colliders(
        self, position_overrides: Mapping[str, tuple[float, float]] | None = None
    ) -> tuple[ColliderOutline, ...]:
        if not self.colliders:
            return ()
        if self.render_context is None:
            return self.colliders
        index = self.collider_spatial_index
        if index is None:
            index = SpatialIndex2D(
                (ordinal, collider.world_bounds)
                for ordinal, collider in enumerate(self.colliders)
            )
            object.__setattr__(self, "collider_spatial_index", index)
            object.__setattr__(
                self,
                "collider_ordinals_by_id",
                {collider.entity_id: ordinal for ordinal, collider in enumerate(self.colliders)},
            )
        ordinals = set(index.query(_world_query_bounds(self.render_context, 1.0, 0.0)))
        if position_overrides:
            ordinals.update(
                ordinal
                for entity_id in position_overrides
                if (ordinal := self.collider_ordinals_by_id.get(entity_id)) is not None
            )
        return tuple(
            replace(collider, position=position_overrides[collider.entity_id])
            if position_overrides is not None and collider.entity_id in position_overrides
            else collider
            for ordinal in sorted(ordinals)
            for collider in (self.colliders[ordinal],)
        )


def _render_context(
    scene: Scene,
    viewport: tuple[int, int],
    camera: Any | None,
    resolved_camera: OrthographicCamera | None,
) -> RenderContext | None:
    width, height = viewport
    if width <= 0 or height <= 0:
        return None
    if resolved_camera is not None:
        preview_camera = resolved_camera
    else:
        if camera is not None:
            cam_width = camera._camera.width
            cam_height = cam_width * height / width
        else:
            cam_width = 20.0
            cam_height = 20.0 * height / width
        preview_camera = OrthographicCamera(width=cam_width, height=cam_height)
        preview_camera.apply_dict(scene.camera)
        if camera is not None:
            preview_camera.position = camera.position
            preview_camera.rotation = camera._camera.rotation
    return RenderContext(Viewport(0, 0, width, height), preview_camera)


def reproject_editor_render_target(
    target: EditorRenderTarget,
    scene: Scene | None,
    *,
    viewport: tuple[int, int] = (400, 300),
    camera: Any | None = None,
    resolved_camera: OrthographicCamera | None = None,
    observer: ObservabilityWatcher | None = None,
    preview_items: Mapping[str, tuple[RenderItem, ...]] | None = None,
) -> EditorRenderTarget:
    """Refresh view-dependent clipping while reusing scene-derived frame data."""
    if scene is None:
        return target
    context = _render_context(scene, viewport, camera, resolved_camera)
    if context is None:
        return replace(target, items=(), selected_id=None, render_context=None)
    plan_token = observer.begin("render:plan") if observer is not None else None
    try:
        with observe_stage(observer, "editor.viewport.visibility_selection"):
            items, candidate_count = target.frame._visible_items_with_candidate_count(
                context, preview_items
            )
    finally:
        if observer is not None and plan_token is not None:
            observer.finish(plan_token)
    if observer is not None:
        observer.increment("render:plan", "items_visible", len(items))
        observer.increment("render:plan", "spatial_candidates", candidate_count)
    return replace(target, items=items, render_context=context)


def build_editor_render_target(
    scene: Scene | None,
    *,
    viewport: tuple[int, int] = (400, 300),
    selected_id: str | None = None,
    camera: Any | None = None,
    resolved_camera: OrthographicCamera | None = None,
    interpolator: Any | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
    observer: ObservabilityWatcher | None = None,
    preview_lighting: bool | None = None,
    modulation_entity_ids: Iterable[str] | None = None,
    primary_level_entity_ids: Iterable[str] | None = None,
) -> EditorRenderTarget:
    """Extract the runtime frame once and apply editor preview clipping."""
    if scene is None:
        return EditorRenderTarget(RenderFrame(), (), None)
    extract_token = observer.begin("render:extract") if observer is not None else None
    try:
        frame = extract_render_frame(
            scene,
            interpolator=interpolator,
            interpolation_fraction=interpolation_fraction,
            animated_players=animated_players,
            modulation_entity_ids=modulation_entity_ids,
            primary_level_entity_ids=primary_level_entity_ids,
        )
    finally:
        if observer is not None and extract_token is not None:
            observer.finish(extract_token)
    if observer is not None:
        observer.increment("render:extract", "entities_considered", len(scene.entities))
        observer.increment("render:extract", "items_produced", len(frame.items))
    if preview_lighting is not None:
        if type(preview_lighting) is not bool:
            raise TypeError("preview_lighting must be a bool or None")
        frame = replace(frame, lighting_enabled=preview_lighting)
    unsupported_effects = tuple(
        effect.request.entity_id for effect in frame.submissions if isinstance(effect, RenderEffect)
    )
    context = _render_context(scene, viewport, camera, resolved_camera)
    if context is None:
        return EditorRenderTarget(frame, (), None, unsupported_effects=unsupported_effects)
    plan_token = observer.begin("render:plan") if observer is not None else None
    try:
        with observe_stage(observer, "editor.viewport.visibility_selection"):
            items, candidate_count = frame._visible_items_with_candidate_count(context)
    finally:
        if observer is not None and plan_token is not None:
            observer.finish(plan_token)
    if observer is not None:
        observer.increment("render:plan", "items_visible", len(items))
        observer.increment("render:plan", "spatial_candidates", candidate_count)
    entity_ids = {entity.entity_id for entity in scene.entities}
    colliders: list[ColliderOutline] = []
    for entity in scene.entities:
        collider = entity.get_component(ColliderComponent)
        transform = entity.get_component(TransformComponent)
        if entity.enabled and collider is not None and collider.enabled and transform is not None:
            colliders.append(
                ColliderOutline(
                    entity.entity_id,
                    collider.editor_outline,
                    (transform.x + collider.offset[0], transform.y + collider.offset[1]),
                    is_area=entity.get_component(AreaComponent) is not None,
                )
            )
    collider_tuple = tuple(colliders)
    collider_index = SpatialIndex2D(
        (index, collider.world_bounds) for index, collider in enumerate(collider_tuple)
    )
    return EditorRenderTarget(
        frame,
        items,
        selected_id if selected_id in entity_ids else None,
        collider_tuple,
        unsupported_effects,
        context,
        collider_index,
        {collider.entity_id: index for index, collider in enumerate(collider_tuple)},
    )
