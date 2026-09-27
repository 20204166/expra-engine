"""Convert scene visuals into the renderer-neutral render contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.canvas_effects import resolve_canvas_modulation
from expra_engine.runtime.lighting_2d import Light2DComponent
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.material_lighting import MaterialLightResponse
from expra_engine.runtime.rendering import (
    Color,
    LightDescriptor,
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
    scene: Scene,
    entity: Entity,
    interpolator: TransformInterpolator | None = None,
    interpolation_fraction: float = 0.0,
) -> Transform:
    if interpolator is not None:
        try:
            result = interpolator.sample_world(entity.entity_id, interpolation_fraction)
        except KeyError:
            pass
        else:
            return result
    pose = scene.world_transform(entity.entity_id)
    return Transform(
        position=(pose.position[0], pose.position[1], 0.0),
        rotation=pose.rotation,
        scale=(pose.scale[0], pose.scale[1], 1.0),
    )


def _item(
    entity: Entity,
    visual: object,
    transform: Transform,
    player: AnimatedSpritePlayer2D | None = None,
    light_response: MaterialLightResponse | None = None,
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
            light_response=light_response,
        )
        payload = visual.to_dict()
        layer = visual.layer
    elif isinstance(visual, SpriteComponent):
        if not visual.asset or visual.width <= 0 or visual.height <= 0:
            raise ValueError("invalid sprite")
        primitive = PrimitiveDescriptor("sprite", (visual.width, visual.height))
        color = visual.tint
        material = MaterialDescriptor(
            color=color,
            tint=color,
            texture_id=visual.asset,
            source_region=visual.region,
            light_response=light_response,
        )
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
            light_response=light_response,
        )
        payload = visual.to_dict()
        layer = view.layer
    elif isinstance(visual, TextComponent):
        if visual.size <= 0 or (visual.max_width is not None and visual.max_width <= 0):
            raise ValueError("invalid text")
        primitive = PrimitiveDescriptor("text", (visual.size, visual.size))
        color = visual.color
        material = MaterialDescriptor(color=color, tint=color, light_response=light_response)
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
        sprite_offset=(
            visual.offset
            if isinstance(visual, SpriteComponent)
            else view.offset
            if isinstance(visual, AnimatedSprite2DComponent) and view is not None
            else (0.0, 0.0)
        ),
        sprite_centered=(
            visual.centered
            if isinstance(visual, SpriteComponent)
            else view.centered
            if isinstance(visual, AnimatedSprite2DComponent) and view is not None
            else True
        ),
        sprite_flip_h=(
            visual.flip_h
            if isinstance(visual, SpriteComponent)
            else view.flip_h
            if isinstance(visual, AnimatedSprite2DComponent) and view is not None
            else False
        ),
        sprite_flip_v=(
            visual.flip_v
            if isinstance(visual, SpriteComponent)
            else view.flip_v
            if isinstance(visual, AnimatedSprite2DComponent) and view is not None
            else False
        ),
        text=TextDescriptor(
            visual.text,
            visual.font,
            visual.size,
            visual.color,
            visual.max_width,
            visual.align,
        )
        if isinstance(visual, TextComponent)
        else None,
    )


def extract_render_frame(
    scene: Scene,
    *,
    elapsed: float = 0.0,
    interpolator: TransformInterpolator | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: Mapping[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
    modulation_entity_ids: Iterable[str] | None = None,
) -> RenderFrame:
    """Convert registered scene visuals into backend-neutral render data."""
    items: list[RenderItem] = []
    lights: list[LightDescriptor] = []
    submissions: list[object] = []
    any_effect = False
    camera_lighting_enabled = scene.camera.get("lighting_enabled", True)
    lighting_enabled = camera_lighting_enabled if type(camera_lighting_enabled) is bool else True
    for entity in scene.entities:
        if not entity.enabled:
            continue
        try:
            transform = _transform(
                scene,
                entity,
                interpolator,
                interpolation_fraction,
            )
        except (TypeError, ValueError, OverflowError):
            continue
        for visual in entity.components:
            if isinstance(visual, Light2DComponent):
                if not visual.enabled or not visual.visible:
                    continue
                try:
                    lights.append(
                        LightDescriptor(
                            entity.entity_id,
                            visual.kind,
                            transform.position,
                            visual.color,
                            visual.energy,
                            visual.radius * max(abs(transform.scale[0]), abs(transform.scale[1])),
                            visual.falloff,
                            direction_degrees=transform.rotation,
                            cone_angle=visual.cone_angle,
                        )
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
                continue
            if isinstance(
                visual,
                (PrimitiveComponent, SpriteComponent, TextComponent, AnimatedSprite2DComponent),
            ):
                if not visual.enabled or not visual.visible:
                    continue
                try:
                    item = _item(
                        entity,
                        visual,
                        transform,
                        animated_players.get(visual)
                        if animated_players and isinstance(visual, AnimatedSprite2DComponent)
                        else None,
                        (
                            material.response
                            if (material := entity.get_component(MaterialComponent)) is not None
                            and material.enabled
                            else None
                        ),
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
        modulation=resolve_canvas_modulation(scene, entity_ids=modulation_entity_ids).color,
        submissions=tuple(submissions) if any_effect else (),
        lights=tuple(lights),
        lighting_enabled=lighting_enabled,
    )
