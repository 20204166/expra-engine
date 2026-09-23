"""Convert scene visuals into the renderer-neutral render contract."""

from __future__ import annotations

from collections.abc import Mapping

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.canvas_effects import resolve_canvas_modulation
from expra_engine.runtime.rendering import (
    Color,
    MaterialDescriptor,
    PrimitiveDescriptor,
    RenderFrame,
    RenderItem,
    RenderPhase,
    TextDescriptor,
    Transform,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureComponent,
    ScreenTextureDrawRequest,
    render_phase_from_value,
)
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.visual_components import (
    PrimitiveComponent,
    SpriteComponent,
    TextComponent,
)

__all__ = ("extract_render_frame",)


def _transform(
    entity: Entity,
    entities: dict[str, Entity],
    active: set[str],
    interpolator: TransformInterpolator | None = None,
    interpolation_fraction: float = 0.0,
) -> Transform:
    if entity.entity_id in active:
        raise ValueError("cyclic entity hierarchy")
    active.add(entity.entity_id)
    if interpolator is not None:
        try:
            result = interpolator.sample_world(entity.entity_id, interpolation_fraction)
        except KeyError:
            pass
        else:
            active.remove(entity.entity_id)
            return result
    local = entity.get_component(TransformComponent)
    result = Transform(
        position=(local.x, local.y, 0.0),
        rotation=local.rotation,
        scale=(local.scale_x, local.scale_y, 1.0),
    ) if local is not None and local.enabled else Transform()
    if entity.parent_id is not None:
        parent = entities.get(entity.parent_id)
        if parent is not None:
            result = _transform(
                parent,
                entities,
                active,
                interpolator,
                interpolation_fraction,
            ).compose(result)
    active.remove(entity.entity_id)
    return result


def _item(
    entity: Entity,
    visual: object,
    transform: Transform,
    player: AnimatedSpritePlayer2D | None = None,
) -> RenderItem:
    if isinstance(visual, PrimitiveComponent):
        if visual.kind not in {"point", "rectangle", "circle", "rounded_rectangle"}:
            raise ValueError("unsupported primitive kind")
        if visual.width <= 0 or visual.height <= 0 or visual.outline_width < 0:
            raise ValueError("invalid primitive dimensions")
        primitive = PrimitiveDescriptor(visual.kind, (visual.width, visual.height), visual.radius)
        color = visual.fill
        material = MaterialDescriptor(
            color=color,
            outline=visual.outline,
            outline_width=visual.outline_width,
            tint=color,
        )
        payload = visual.to_dict()
        layer = visual.layer
    elif isinstance(visual, SpriteComponent):
        if not visual.asset or visual.width <= 0 or visual.height <= 0:
            raise ValueError("invalid sprite")
        primitive = PrimitiveDescriptor("sprite", (visual.width, visual.height))
        color = visual.tint
        material = MaterialDescriptor(color=color, tint=color, texture_id=visual.asset)
        payload = visual.to_dict()
        layer = visual.layer
    elif isinstance(visual, AnimatedSprite2DComponent):
        player = player or AnimatedSpritePlayer2D(visual)
        view = player.view
        if view is None:
            raise ValueError("animated sprite has no current frame")
        primitive = PrimitiveDescriptor("sprite", (1.0, 1.0))
        color = Color(1.0, 1.0, 1.0, 1.0)
        material = MaterialDescriptor(
            texture_id=view.asset_id,
            source_region=view.region,
        )
        payload = visual.to_dict()
        layer = view.layer
    elif isinstance(visual, TextComponent):
        if visual.size <= 0 or (visual.max_width is not None and visual.max_width <= 0):
            raise ValueError("invalid text")
        primitive = PrimitiveDescriptor("text", (visual.size, visual.size))
        color = visual.color
        material = MaterialDescriptor(color=color, tint=color)
        payload = visual.to_dict()
        layer = visual.layer
    else:
        raise ValueError("unsupported visual component")
    phase = RenderPhase.OPAQUE if color.alpha >= 1.0 else RenderPhase.TRANSPARENT
    return RenderItem(
        entity.entity_id,
        primitive,
        transform,
        material=material,
        phase=phase,
        layer=entity.layer + layer,
        payload=payload,
        sprite_offset=view.offset if isinstance(visual, AnimatedSprite2DComponent) and view is not None else (0.0, 0.0),
        sprite_centered=view.centered if isinstance(visual, AnimatedSprite2DComponent) and view is not None else True,
        sprite_flip_h=view.flip_h if isinstance(visual, AnimatedSprite2DComponent) and view is not None else False,
        sprite_flip_v=view.flip_v if isinstance(visual, AnimatedSprite2DComponent) and view is not None else False,
        text=TextDescriptor(
            visual.text,
            visual.font,
            visual.size,
            visual.color,
            visual.max_width,
            visual.align,
        ) if isinstance(visual, TextComponent) else None,
    )


def extract_render_frame(
    scene: Scene,
    *,
    elapsed: float = 0.0,
    interpolator: TransformInterpolator | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: Mapping[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
) -> RenderFrame:
    """Convert registered scene visuals into backend-neutral render data."""
    entities = {entity.entity_id: entity for entity in scene.entities}
    items: list[RenderItem] = []
    submissions: list[object] = []
    any_effect = False
    for entity in scene.entities:
        if not entity.enabled:
            continue
        try:
            transform = _transform(
                entity,
                entities,
                set(),
                interpolator,
                interpolation_fraction,
            )
        except (TypeError, ValueError, OverflowError):
            continue
        for visual in entity.components:
            if isinstance(
                visual, (PrimitiveComponent, SpriteComponent, TextComponent, AnimatedSprite2DComponent)
            ):
                if not visual.enabled or not visual.visible:
                    continue
                try:
                    item = _item(
                        entity,
                        visual,
                        transform,
                        animated_players.get(visual) if animated_players else None,
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
                items.append(item)
                submissions.append(item)
                continue

            if not isinstance(visual, (BackBufferCopyComponent, ScreenTextureComponent)):
                continue

            if not visual.enabled or (
                isinstance(visual, ScreenTextureComponent) and not visual.visible
            ):
                continue

            try:
                phase = render_phase_from_value(visual.phase)
                layer = entity.layer + visual.layer
                if isinstance(visual, BackBufferCopyComponent):
                    request = BackBufferCopyRequest(
                        entity.entity_id,
                        visual.capture_id,
                        visual.copy_mode,
                        transform,
                        visual.rect,
                    )
                else:
                    request = ScreenTextureDrawRequest(
                        entity.entity_id,
                        visual.capture_id,
                        transform,
                        visual.width,
                        visual.height,
                        visual.uv_rect,
                        visual.filter,
                        visual.lod,
                        visual.tint,
                        visual.opacity,
                    )
                effect = RenderEffect(request, phase, layer)
            except (TypeError, ValueError, OverflowError):
                continue
            submissions.append(effect)
            any_effect = True
    return RenderFrame(
        tuple(items),
        elapsed=elapsed,
        modulation=resolve_canvas_modulation(scene).color,
        submissions=tuple(submissions) if any_effect else (),
    )
