"""Convert scene visuals into the renderer-neutral render contract."""

from __future__ import annotations

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.rendering import (
    MaterialDescriptor,
    PrimitiveDescriptor,
    RenderFrame,
    RenderItem,
    RenderPhase,
    Transform,
)
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent, TextComponent

__all__ = ("extract_render_frame",)


def _transform(entity: Entity, entities: dict[str, Entity], active: set[str]) -> Transform:
    if entity.entity_id in active:
        raise ValueError("cyclic entity hierarchy")
    active.add(entity.entity_id)
    local = entity.get_component(TransformComponent)
    result = Transform(
        position=(local.x, local.y, 0.0),
        rotation=local.rotation,
        scale=(local.scale_x, local.scale_y, 1.0),
    ) if local is not None and local.enabled else Transform()
    if entity.parent_id is not None:
        parent = entities.get(entity.parent_id)
        if parent is not None:
            result = _transform(parent, entities, active).compose(result)
    active.remove(entity.entity_id)
    return result


def _item(entity: Entity, visual: object, transform: Transform) -> RenderItem:
    if isinstance(visual, PrimitiveComponent):
        if visual.kind not in {"point", "rectangle", "circle", "rounded_rectangle"}:
            raise ValueError("unsupported primitive kind")
        if visual.width <= 0 or visual.height <= 0 or visual.outline_width < 0:
            raise ValueError("invalid primitive dimensions")
        primitive = PrimitiveDescriptor(visual.kind, (visual.width, visual.height), visual.radius)
        color = visual.fill
        payload = visual.to_dict()
        layer = visual.layer
    elif isinstance(visual, SpriteComponent):
        if not visual.asset or visual.width <= 0 or visual.height <= 0:
            raise ValueError("invalid sprite")
        primitive = PrimitiveDescriptor("sprite", (visual.width, visual.height))
        color = visual.tint
        payload = visual.to_dict()
        layer = visual.layer
    elif isinstance(visual, TextComponent):
        if not visual.text or visual.size <= 0 or (visual.max_width is not None and visual.max_width <= 0):
            raise ValueError("invalid text")
        primitive = PrimitiveDescriptor("text", (visual.size, visual.size))
        color = visual.color
        payload = visual.to_dict()
        layer = visual.layer
    else:
        raise ValueError("unsupported visual component")
    phase = RenderPhase.OPAQUE if color.alpha >= 1.0 else RenderPhase.TRANSPARENT
    return RenderItem(
        entity.entity_id,
        primitive,
        transform,
        material=MaterialDescriptor(color=color),
        phase=phase,
        layer=entity.layer + layer,
        payload=payload,
    )


def extract_render_frame(scene: Scene, *, elapsed: float = 0.0) -> RenderFrame:
    """Convert registered scene visuals into backend-neutral render data."""
    entities = {entity.entity_id: entity for entity in scene.entities}
    items: list[RenderItem] = []
    for entity in scene.entities:
        if not entity.enabled:
            continue
        try:
            transform = _transform(entity, entities, set())
        except (TypeError, ValueError, OverflowError):
            continue
        for visual in entity.components:
            if isinstance(visual, (PrimitiveComponent, SpriteComponent, TextComponent)):
                if visual.enabled and visual.visible:
                    try:
                        items.append(_item(entity, visual, transform))
                    except (TypeError, ValueError, OverflowError):
                        continue
    return RenderFrame(tuple(items), elapsed=elapsed)
