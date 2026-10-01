"""Convert scene visuals into the renderer-neutral render contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.camera_mount import VIEWPORT_ANCHORS, CameraMountComponent
from expra_engine.runtime.canvas_effects import resolve_canvas_modulation
from expra_engine.runtime.lighting_2d import Light2DComponent
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.material_lighting import MaterialLightResponse
from expra_engine.runtime.rendering import (
    SUPPORTED_PRIMITIVE_KINDS,
    Color,
    LightDescriptor,
    MaterialDescriptor,
    NormalMapDescriptor,
    PrimitiveDescriptor,
    RenderFrame,
    RenderItem,
    RenderPhase,
    RenderSpace,
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


def _local_transform(
    entity: Entity,
    interpolator: TransformInterpolator | None,
    interpolation_fraction: float,
) -> Transform:
    if interpolator is not None:
        try:
            return interpolator.sample_local(entity.entity_id, interpolation_fraction)
        except KeyError:
            pass
    component = entity.get_component(TransformComponent)
    if component is None or not component.enabled:
        return Transform()
    return Transform(
        position=(component.x, component.y, 0.0),
        rotation=component.rotation,
        scale=(component.scale_x, component.scale_y, 1.0),
    )


def _mount_transforms(
    scene: Scene,
    interpolator: TransformInterpolator | None,
    interpolation_fraction: float,
) -> dict[str, tuple[Entity, CameraMountComponent, Transform]]:
    """Resolve the nearest mount and local Transform in one hierarchy traversal.

    The root's own Transform is deliberately replaced by identity. Each
    descendant's local pose is composed once and cached for this extraction,
    preventing a deep HUD tree from repeating all ancestor compositions for
    every visual descendant.
    """
    mounts: dict[str, tuple[Entity, CameraMountComponent, Transform]] = {}
    for entity in scene.walk_hierarchy():
        component = entity.get_component(CameraMountComponent)
        if component is not None and component.enabled:
            mounts[entity.entity_id] = (entity, component, Transform())
            continue
        if entity.parent_id is None:
            continue
        parent_mount = mounts.get(entity.parent_id)
        if parent_mount is None:
            continue
        root, mount, parent_transform = parent_mount
        local = _local_transform(entity, interpolator, interpolation_fraction)
        mounts[entity.entity_id] = (root, mount, parent_transform.compose(local))
    return mounts


def _item(
    entity: Entity,
    visual: object,
    transform: Transform,
    player: AnimatedSpritePlayer2D | None = None,
    light_response: MaterialLightResponse | None = None,
    normal_map: NormalMapDescriptor | None = None,
    *,
    space: RenderSpace = RenderSpace.WORLD,
    viewport_anchor: tuple[float, float] | None = None,
    viewport_offset: tuple[float, float] = (0.0, 0.0),
) -> RenderItem:
    if isinstance(visual, PrimitiveComponent):
        if visual.kind not in SUPPORTED_PRIMITIVE_KINDS:
            raise ValueError("unsupported primitive kind")
        if visual.outline_width < 0:
            raise ValueError("invalid primitive dimensions")
        if visual.kind in ("polygon", "line"):
            points = visual.points
            if visual.kind == "polygon" and (points is None or len(points) < 3):
                raise ValueError("polygon primitive requires at least three points")
            if visual.kind == "line" and (points is None or len(points) != 2):
                raise ValueError("line primitive requires exactly two points")
            if points is None:
                raise ValueError("primitive points are required")
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            width = max(max(xs) - min(xs), 1e-6)
            height = max(max(ys) - min(ys), 1e-6)
            primitive = PrimitiveDescriptor(
                visual.kind, (width, height), None, tuple(points), visual.thickness
            )
        else:
            if visual.width <= 0 or visual.height <= 0:
                raise ValueError("invalid primitive dimensions")
            primitive = PrimitiveDescriptor(
                visual.kind, (visual.width, visual.height), visual.radius
            )
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
            normal_map=normal_map,
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
            normal_map=normal_map,
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
    phase = (
        RenderPhase.OVERLAY
        if space is RenderSpace.VIEWPORT
        else RenderPhase.OPAQUE
        if color.alpha >= 1.0
        else RenderPhase.TRANSPARENT
    )
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
        space=space,
        viewport_anchor=viewport_anchor,
        viewport_offset=viewport_offset,
    )


def extract_render_frame(
    scene: Scene,
    *,
    elapsed: float = 0.0,
    interpolator: TransformInterpolator | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: Mapping[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
    modulation_entity_ids: Iterable[str] | None = None,
    primary_level_entity_ids: Iterable[str] | None = None,
) -> RenderFrame:
    """Convert registered scene visuals into backend-neutral render data."""
    items: list[RenderItem] = []
    lights: list[LightDescriptor] = []
    submissions: list[object] = []
    any_effect = False
    mounted_transforms = _mount_transforms(scene, interpolator, interpolation_fraction)
    primary_entities = (
        frozenset(primary_level_entity_ids)
        if primary_level_entity_ids is not None
        else None
    )
    camera_lighting_enabled = scene.camera.get("lighting_enabled", True)
    lighting_enabled = camera_lighting_enabled if type(camera_lighting_enabled) is bool else True
    for entity in scene.entities:
        if not entity.enabled:
            continue
        mount = mounted_transforms.get(entity.entity_id)
        if mount is None:
            try:
                world_transform = _transform(
                    scene,
                    entity,
                    interpolator,
                    interpolation_fraction,
                )
            except (TypeError, ValueError, OverflowError):
                continue
            render_transform = world_transform
            render_space = RenderSpace.WORLD
            viewport_anchor = None
            viewport_offset = (0.0, 0.0)
        else:
            mount_root, mount_component, render_transform = mount
            if not mount_root.enabled or (
                primary_entities is not None and mount_root.entity_id not in primary_entities
            ):
                continue
            render_space = RenderSpace.VIEWPORT
            viewport_anchor = VIEWPORT_ANCHORS[mount_component.mount]
            viewport_offset = (mount_component.x, mount_component.y)
            world_transform = None
        for visual in entity.components:
            if isinstance(visual, Light2DComponent):
                if not visual.enabled or not visual.visible:
                    continue
                if world_transform is None:
                    try:
                        world_transform = _transform(
                            scene,
                            entity,
                            interpolator,
                            interpolation_fraction,
                        )
                    except (TypeError, ValueError, OverflowError):
                        continue
                try:
                    lights.append(
                        LightDescriptor(
                            entity.entity_id,
                            visual.kind,
                            world_transform.position,
                            visual.color,
                            visual.energy,
                            visual.radius
                            * max(abs(world_transform.scale[0]), abs(world_transform.scale[1])),
                            visual.falloff,
                            direction_degrees=world_transform.rotation,
                            cone_angle=visual.cone_angle,
                            height=visual.height,
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
                        render_transform,
                        animated_players.get(visual)
                        if animated_players and isinstance(visual, AnimatedSprite2DComponent)
                        else None,
                        (
                            material.response
                            if (material := entity.get_component(MaterialComponent)) is not None
                            and material.enabled
                            else None
                        ),
                        (
                            material.normal_map_descriptor
                            if material is not None
                            and material.enabled
                            and isinstance(visual, (SpriteComponent, AnimatedSprite2DComponent))
                            else None
                        ),
                        space=render_space,
                        viewport_anchor=viewport_anchor,
                        viewport_offset=viewport_offset,
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

            if world_transform is None:
                try:
                    world_transform = _transform(
                        scene,
                        entity,
                        interpolator,
                        interpolation_fraction,
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
            try:
                phase = render_phase_from_value(visual.phase)
                layer = entity.layer + visual.layer
                if isinstance(visual, BackBufferCopyComponent):
                    request = BackBufferCopyRequest(
                        entity.entity_id,
                        visual.capture_id,
                        visual.copy_mode,
                        world_transform,
                        visual.rect,
                    )
                else:
                    request = ScreenTextureDrawRequest(
                        entity.entity_id,
                        visual.capture_id,
                        world_transform,
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
