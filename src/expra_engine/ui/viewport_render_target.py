"""Renderer-neutral render target construction for the editor viewport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
)
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderItem,
    Viewport,
)
from expra_engine.runtime.screen_texture import RenderEffect

__all__ = ("ColliderOutline", "EditorRenderTarget", "build_editor_render_target")


@dataclass(frozen=True)
class ColliderOutline:
    entity_id: str
    outline: dict[str, Any]
    position: tuple[float, float]


@dataclass(frozen=True)
class EditorRenderTarget:
    """Renderer-neutral preview data plus editor-only overlay inputs."""

    frame: RenderFrame
    items: tuple[RenderItem, ...]
    selected_id: str | None
    colliders: tuple[ColliderOutline, ...] = ()
    unsupported_effects: tuple[str, ...] = ()


def build_editor_render_target(
    scene: Scene | None,
    *,
    viewport: tuple[int, int] = (400, 300),
    selected_id: str | None = None,
    camera: Any | None = None,
    interpolator: Any | None = None,
    interpolation_fraction: float = 0.0,
    animated_players: dict[AnimatedSprite2DComponent, AnimatedSpritePlayer2D] | None = None,
) -> EditorRenderTarget:
    """Extract the runtime frame once and apply editor preview clipping."""
    if scene is None:
        return EditorRenderTarget(RenderFrame(), (), None)
    frame = extract_render_frame(
        scene,
        interpolator=interpolator,
        interpolation_fraction=interpolation_fraction,
        animated_players=animated_players,
    )
    unsupported_effects = tuple(
        effect.request.entity_id for effect in frame.submissions if isinstance(effect, RenderEffect)
    )
    width, height = viewport
    if width <= 0 or height <= 0:
        return EditorRenderTarget(frame, (), None, unsupported_effects=unsupported_effects)
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
    context = RenderContext(Viewport(0, 0, width, height), preview_camera)
    items = frame.visible_items(context)
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
                )
            )
    return EditorRenderTarget(
        frame,
        items,
        selected_id if selected_id in entity_ids else None,
        tuple(colliders),
        unsupported_effects,
    )
