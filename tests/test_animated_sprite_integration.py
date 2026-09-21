"""Integration tests for AnimatedSprite2D ownership and rendering seams."""

import json
from types import SimpleNamespace

from expra_engine.core.component import component_from_dict, registered_component_types
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.engine import Engine
from expra_engine.core.scene import Scene
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    AnimatedSpritePlayer2D,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
    SpriteLoopMode,
)
from expra_engine.runtime.animation import SpriteRegion
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import RenderContext, Viewport


def _frames() -> SpriteFrames2D:
    return SpriteFrames2D(
        {
            "walk": SpriteAnimation2D(
                (
                    SpriteFrame2D("hero.png", region=SpriteRegion(0, 0, 16, 16)),
                    SpriteFrame2D("hero.png", region=SpriteRegion(16, 0, 16, 16)),
                ),
                speed_fps=10.0,
                loop_mode=SpriteLoopMode.LINEAR,
            )
        }
    )


def test_animated_component_is_registered_with_inspector_metadata() -> None:
    component = AnimatedSprite2DComponent(_frames(), animation="walk")

    assert dict(registered_component_types())["animated_sprite"] is type(component)
    assert component_type_spec("animated_sprite").cls is type(component)
    assert {field.name for field in component_type_spec("animated_sprite").fields} >= {
        "frames",
        "animation",
        "autoplay",
        "frame",
        "frame_progress",
        "speed_scale",
        "centered",
        "offset",
        "flip_h",
        "flip_v",
        "layer",
        "visible",
    }


def test_scene_json_round_trip_keeps_configuration_without_runtime_state() -> None:
    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    entity.add_component(
        AnimatedSprite2DComponent(_frames(), animation="walk", autoplay="walk", frame=1)
    )

    payload = json.loads(json.dumps(scene.to_dict()))
    restored = Scene.from_dict(payload)

    assert restored.to_dict() == scene.to_dict()
    assert "playing" not in json.dumps(payload)
    assert isinstance(
        component_from_dict(entity.components[0].to_dict()), AnimatedSprite2DComponent
    )


def test_engine_runtime_system_starts_autoplay_and_advances_active_scene_players() -> None:
    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    entity.add_component(AnimatedSprite2DComponent(_frames(), animation="walk", autoplay="walk"))
    engine = Engine()
    engine.set_scene(scene)

    engine.play()
    engine.tick(0.12)

    runtime_entity = engine.active_scene.find_entity("hero") if engine.active_scene else None
    assert runtime_entity is not None
    runtime_component = runtime_entity.get_component(AnimatedSprite2DComponent)
    assert runtime_component is not None
    player = engine.animated_sprite_system.player_for(runtime_component)
    assert player is not None
    assert player.playing
    assert player.frame == 1
    engine.stop()
    assert engine.animated_sprite_system.players == {}


def test_runtime_players_reconcile_removed_entities_and_scene_replacement() -> None:
    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    component = AnimatedSprite2DComponent(_frames(), autoplay="walk")
    entity.add_component(component)
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    assert engine.active_scene is not None
    engine.active_scene.remove_entity(entity.entity_id)
    engine.tick(0.0)
    assert engine.animated_sprite_system.players == {}

    replacement = Scene("replacement")
    other = replacement.create_entity("other", entity_id="other")
    other_component = AnimatedSprite2DComponent(_frames(), autoplay="walk")
    other.add_component(other_component)
    engine.replace_scene(replacement)
    assert engine.animated_sprite_system.player_for(component) is None
    assert engine.animated_sprite_system.player_for(other_component) is not None
    engine.stop()


def test_runtime_system_ignores_disabled_entities_and_components() -> None:
    scene = Scene("animated")
    disabled_entity = scene.create_entity("disabled", entity_id="disabled", enabled=False)
    disabled_entity.add_component(AnimatedSprite2DComponent(_frames(), autoplay="walk"))
    disabled_component_entity = scene.create_entity("component", entity_id="component")
    component = AnimatedSprite2DComponent(_frames(), autoplay="walk", enabled=False)
    disabled_component_entity.add_component(component)
    engine = Engine()
    engine.set_scene(scene)
    engine.play()

    assert engine.animated_sprite_system.players == {}
    disabled_entity = engine.active_scene.find_entity("disabled") if engine.active_scene else None
    assert disabled_entity is not None
    disabled_entity.enabled = True
    runtime_disabled_component = disabled_entity.get_component(AnimatedSprite2DComponent)
    assert runtime_disabled_component is not None
    runtime_component_entity = (
        engine.active_scene.find_entity("component") if engine.active_scene else None
    )
    assert runtime_component_entity is not None
    runtime_component = runtime_component_entity.get_component(AnimatedSprite2DComponent)
    assert runtime_component is not None
    runtime_component.enabled = True
    engine.tick(0.0)
    assert set(engine.animated_sprite_system.players) == {
        runtime_disabled_component,
        runtime_component,
    }


def test_runtime_system_reconciles_changed_frame_collections_without_serializing_player_state() -> (
    None
):
    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    component = AnimatedSprite2DComponent(_frames(), autoplay="walk")
    entity.add_component(component)
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    runtime_entity = engine.active_scene.find_entity("hero") if engine.active_scene else None
    assert runtime_entity is not None
    runtime_component = runtime_entity.get_component(AnimatedSprite2DComponent)
    assert runtime_component is not None
    runtime_component.frames = SpriteFrames2D()
    engine.tick(0.0)

    player = engine.animated_sprite_system.player_for(runtime_component)
    assert player is not None
    assert player.view is None
    assert "playing" not in json.dumps(engine.edit_scene.to_dict() if engine.edit_scene else {})


def test_extractor_consumes_player_view_without_bypassing_render_contract() -> None:
    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    component = AnimatedSprite2DComponent(
        _frames(), animation="walk", centered=False, offset=(2.0, -1.0), flip_h=True, flip_v=True
    )
    entity.add_component(component)
    player = AnimatedSpritePlayer2D(component)
    frame = extract_render_frame(scene, animated_players={component: player})

    item = frame.items[0]
    assert item.material.texture_id == "hero.png"
    assert item.material.source_region == SpriteRegion(0, 0, 16, 16)
    assert item.sprite_centered is False
    assert item.sprite_offset == (2.0, -1.0)
    assert item.sprite_flip_h and item.sprite_flip_v


class _Texture:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def subsurface(self, region: object) -> "_Texture":
        self.calls.append(("subsurface", region))
        return self

    def get_size(self) -> tuple[int, int]:
        return (16, 16)


def test_pygame_backend_consumes_atlas_and_flip_contract() -> None:
    texture = _Texture()
    surface = SimpleNamespace(blit=lambda *_args: None)
    draw = SimpleNamespace(rect=lambda *_args: None)
    transform = SimpleNamespace(
        flip=lambda value, horizontal, vertical: (
            texture.calls.append(("flip", horizontal, vertical)) or value
        ),
        smoothscale=lambda value, _size: value,
        rotate=lambda value, _angle: value,
    )
    pygame = SimpleNamespace(draw=draw, transform=transform, Rect=lambda *values: values)
    renderer = PygameRenderer(pygame, surface, resource_provider=lambda _asset: texture)
    renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

    scene = Scene("animated")
    entity = scene.create_entity("hero", entity_id="hero")
    component = AnimatedSprite2DComponent(_frames(), animation="walk", flip_h=True, flip_v=True)
    entity.add_component(component)
    renderer.render(
        extract_render_frame(scene, animated_players={component: AnimatedSpritePlayer2D(component)})
    )

    assert texture.calls == [("subsurface", (0, 0, 16, 16)), ("flip", True, True)]
