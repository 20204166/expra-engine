from __future__ import annotations

from concurrent.futures import Executor, Future
from typing import Any, cast

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.project import Project
from expra_engine.core.scene import Level, Scene, SceneInstanceComponent, resolve_scene_instances
from expra_engine.core.world import LevelDescriptor, World, WorldStreamingSettings
from expra_engine.editor.commands import SetComponentPropertyCommand
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.lighting_2d import Light2DComponent
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.material_lighting import LightingMode, MaterialLightResponse
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    MaterialDescriptor,
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderItem,
    TextDescriptor,
    Transform,
    Viewport,
)
from expra_engine.runtime.screen_texture import BackBufferCopyComponent
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent
from expra_engine.runtime.world_streaming import WorldStreamingSystem


def test_material_light_response_has_a_validated_neutral_lit_default() -> None:
    response = MaterialLightResponse()

    assert response.mode is LightingMode.LIT
    assert response.receives_light is True
    assert response.ambient_response == 1.0
    assert response.diffuse == 1.0
    assert response.emission == 0.0
    assert response.toon_steps == 3


def test_render_material_rejects_noncanonical_light_response_values() -> None:
    with pytest.raises(TypeError, match="MaterialLightResponse"):
        MaterialDescriptor(light_response=cast(Any, object()))


def test_unlit_and_toon_responses_have_explicit_light_semantics() -> None:
    unlit = MaterialLightResponse(mode=LightingMode.UNLIT)
    toon = MaterialLightResponse(mode=LightingMode.TOON, toon_steps=4)

    assert unlit.receives_light is False
    assert toon.receives_light is True
    assert toon.toon_steps == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ambient_response": -0.1},
        {"ambient_response": float("nan")},
        {"diffuse": 1.1},
        {"emission": -1.0},
        {"toon_steps": 1},
        {"mode": "specular"},
        {"emission_color": (1.0, 0.5, 0.0)},
    ],
)
def test_material_light_response_rejects_unsupported_or_out_of_range_values(kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        MaterialLightResponse(**kwargs)


def test_entity_material_response_serializes_authors_and_reaches_render_contract() -> None:
    data = {
        "type": "material",
        "enabled": True,
        "mode": "toon",
        "ambient_response": 0.8,
        "diffuse": 0.7,
        "emission": 0.25,
        "emission_color": [1.0, 0.1, 0.5, 1.0],
        "toon_steps": 4,
    }
    component = component_from_dict(data)
    assert isinstance(component, MaterialComponent)
    assert component.to_dict() == data
    assert {field.name for field in component_type_spec("material").fields} >= {
        "mode",
        "ambient_response",
        "diffuse",
        "emission",
        "emission_color",
        "toon_steps",
    }

    scene = Scene("material")
    visual = scene.create_entity("visual")
    visual.add_component(PrimitiveComponent(fill=(1.0, 1.0, 1.0)))
    visual.add_component(component)

    response = extract_render_frame(scene).items[0].material.light_response
    assert response is not None
    assert response == MaterialLightResponse(
        mode=LightingMode.TOON,
        ambient_response=0.8,
        diffuse=0.7,
        emission=0.25,
        emission_color=component.response.emission_color,
        toon_steps=4,
    )


def test_material_properties_are_editable_through_the_existing_inspector_command() -> None:
    scene = Scene("inspector")
    entity = scene.create_entity("visual")
    material = MaterialComponent()
    entity.add_component(material)

    SetComponentPropertyCommand(
        scene, entity.entity_id, MaterialComponent, "mode", "toon"
    ).execute()
    SetComponentPropertyCommand(
        scene, entity.entity_id, MaterialComponent, "ambient_response", 0.25
    ).execute()

    assert material.response.mode is LightingMode.TOON
    assert material.response.ambient_response == 0.25


def test_material_response_absence_retains_the_legacy_render_contract() -> None:
    scene = Scene("legacy")
    entity = scene.create_entity("visual")
    entity.add_component(PrimitiveComponent())

    assert extract_render_frame(scene).items[0].material.light_response is None


def test_scene_instance_materializes_the_source_material_response(tmp_path) -> None:
    source = Scene("reusable prop")
    prop = source.create_entity("prop")
    prop.add_component(PrimitiveComponent())
    prop.add_component(MaterialComponent(mode="toon", ambient_response=0.4, toon_steps=4))
    owner = Scene("level")
    owner.create_entity("prop instance").add_component(
        SceneInstanceComponent("scenes/prop.scene.pb")
    )

    resolve_scene_instances(owner, resolve_source=lambda _path: source)

    frame = extract_render_frame(owner)
    assert len(frame.items) == 1
    assert frame.items[0].material.light_response == MaterialLightResponse(
        mode=LightingMode.TOON,
        ambient_response=0.4,
        toon_steps=4,
    )

    project = Project.create("instance material", tmp_path / "instance-material")
    project.save_document(source, "scenes/prop.scene.pb")
    authored_level = Level("Instance Level", scene_id="instance-level")
    instance = authored_level.create_entity("reusable prop instance")
    instance.add_component(SceneInstanceComponent("scenes/prop.scene.pb"))
    project.save_document(authored_level, "levels/instance.level.pb")
    loaded_level = project.load_scene("levels/instance.level.pb")
    loaded_frame = extract_render_frame(loaded_level)
    assert loaded_frame.items[0].material.light_response == frame.items[0].material.light_response


def test_standalone_level_and_world_activation_keep_material_responses(tmp_path) -> None:
    town = Level("Town", scene_id="town")
    town_visual = town.create_entity("town visual", entity_id="town-visual")
    town_visual.add_component(PrimitiveComponent())
    town_visual.add_component(MaterialComponent(mode="unlit"))
    forest = Level("Forest", scene_id="forest")
    forest_visual = forest.create_entity("forest visual", entity_id="forest-visual")
    forest_visual.add_component(PrimitiveComponent())
    forest_visual.add_component(MaterialComponent(mode="toon", toon_steps=4))
    town_response = extract_render_frame(town).items[0].material.light_response
    assert town_response is not None and town_response.mode is LightingMode.UNLIT

    project = Project.create("materials", tmp_path / "materials")
    project.save_document(town, "levels/town.level.pb")
    project.save_document(forest, "levels/forest.level.pb")

    class ImmediateExecutor(Executor):
        def submit(self, function, /, *args, **kwargs):
            future = Future()
            future.set_result(function(*args, **kwargs))
            return future

        def shutdown(self, wait=True, *, cancel_futures=False):
            del wait, cancel_futures

    world = World(
        "materials",
        world_id="materials",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(10.0, 0.0)),
        ),
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2),
    )
    system = WorldStreamingSystem(
        project,
        world,
        executor_factory=lambda _workers: ImmediateExecutor(),
    )
    system.start(object())
    try:
        initial = extract_render_frame(system.runtime_scene)
        initial_responses = [item.material.light_response for item in initial.items]
        assert all(response is not None for response in initial_responses)
        assert [response.mode for response in initial_responses if response is not None] == [
            LightingMode.UNLIT
        ]
        system.request_load("forest")
        system.update()
        assert system.activate_level("forest") is True
        active = extract_render_frame(system.runtime_scene)
        active_responses = [item.material.light_response for item in active.items]
        assert all(response is not None for response in active_responses)
        assert {response.mode for response in active_responses if response is not None} == {
            LightingMode.UNLIT,
            LightingMode.TOON,
        }
        assert system.deactivate_level("town") is True
        after_deactivation = extract_render_frame(system.runtime_scene)
        deactivated_responses = [item.material.light_response for item in after_deactivation.items]
        assert all(response is not None for response in deactivated_responses)
        assert [response.mode for response in deactivated_responses if response is not None] == [
            LightingMode.TOON
        ]
    finally:
        system.close()


def test_lit_and_unlit_visuals_respond_independently_to_the_same_light() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("receiver boundary")
    lit = scene.create_entity("lit")
    lit.add_component(TransformComponent(x=-2.0))
    lit.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    lit.add_component(MaterialComponent(mode="lit", ambient_response=0.0))
    unlit = scene.create_entity("unlit")
    unlit.add_component(TransformComponent(x=2.0))
    unlit.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    unlit.add_component(MaterialComponent(mode="unlit"))
    light = scene.create_entity("red light")
    light.add_component(TransformComponent(x=-2.0))
    light.add_component(Light2DComponent(color=(1.0, 0.0, 0.0), radius=3.0))

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))

    lit_pixel = surface.get_at((30, 50))
    unlit_pixel = surface.get_at((70, 50))
    assert lit_pixel.r > 100 and lit_pixel.g < 20 and lit_pixel.b < 20
    assert unlit_pixel.r > 240 and unlit_pixel.g > 240 and unlit_pixel.b > 240


def test_material_scratch_surface_is_released_when_renderer_stops() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("scratch lifecycle")
    entity = scene.create_entity("lit visual")
    entity.add_component(PrimitiveComponent())
    entity.add_component(MaterialComponent(ambient_response=0.5))
    renderer = PygameRenderer(pygame, pygame.Surface((32, 32)), clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 32, 32), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))
    assert renderer._material_scratch is not None

    renderer.stop()

    assert renderer._material_scratch is None


def test_material_bounds_follow_canonical_circle_radius_extent() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("large circle material bounds")
    circle = scene.create_entity("large circle")
    circle.add_component(
        PrimitiveComponent(kind="circle", width=0.5, height=0.5, radius=2.0, fill=(1, 1, 1))
    )
    circle.add_component(MaterialComponent(ambient_response=0.0))
    light = scene.create_entity("edge light")
    light.add_component(TransformComponent(x=1.5))
    light.add_component(Light2DComponent(color=(1.0, 0.0, 0.0), radius=0.75))

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))

    edge = surface.get_at((65, 50))
    assert edge.r > 100 and edge.g < 20 and edge.b < 20


def test_material_text_uses_its_measured_bounds_instead_of_the_full_viewport() -> None:
    import pygame

    pygame.font.init()
    renderer = PygameRenderer(pygame, pygame.Surface((200, 100)))
    context = RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera(width=20.0, height=10.0))
    item = RenderItem(
        "label",
        PrimitiveDescriptor("text", (16.0, 16.0)),
        Transform(position=(0.0, 0.0, 0.0)),
        material=MaterialDescriptor(light_response=MaterialLightResponse(ambient_response=0.5)),
        text=TextDescriptor("small label", size=16.0),
    )

    bounds = renderer._material_bounds(item, context, (200, 100))

    assert bounds is not None
    assert bounds.width < 100
    assert bounds.height < 40


def test_canvas_ambient_darkens_lit_material_but_emission_keeps_its_color() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("ambient and emission")
    darkened = scene.create_entity("darkened")
    darkened.add_component(TransformComponent(x=-2.0))
    darkened.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    darkened.add_component(MaterialComponent(ambient_response=1.0))
    glowing = scene.create_entity("glowing")
    glowing.add_component(TransformComponent(x=2.0))
    glowing.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    glowing.add_component(
        MaterialComponent(
            ambient_response=0.0,
            emission=0.8,
            emission_color=(1.0, 0.1, 0.5),
        )
    )
    receiver = scene.create_entity("light receiver")
    receiver.add_component(TransformComponent(x=4.0))
    receiver.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    receiver.add_component(MaterialComponent(ambient_response=0.0))
    scene.create_entity("ambient").add_component(CanvasModulateComponent((0.1, 0.1, 0.1)))

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))

    dark_pixel = surface.get_at((30, 50))
    glow_pixel = surface.get_at((70, 50))
    receiver_without_light = surface.get_at((90, 50))
    assert dark_pixel.r < 40
    assert glow_pixel.r > 180 and glow_pixel.g < 80 and glow_pixel.b > 80
    assert receiver_without_light.r < 20

    torch_light = scene.create_entity("separate torch light")
    torch_light.add_component(TransformComponent(x=2.0))
    torch_light.add_component(Light2DComponent(color=(1.0, 0.2, 0.1), radius=4.0))
    renderer.render(extract_render_frame(scene))
    assert surface.get_at((90, 50)).r > receiver_without_light.r


def test_toon_mode_quantizes_local_diffuse_light_without_a_separate_renderer() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("toon response")
    smooth = scene.create_entity("smooth")
    smooth.add_component(TransformComponent(y=2.0))
    smooth.add_component(PrimitiveComponent(width=8.0, height=1.0, fill=(1, 1, 1)))
    smooth.add_component(MaterialComponent(ambient_response=0.0))
    toon = scene.create_entity("toon")
    toon.add_component(TransformComponent(y=-2.0))
    toon.add_component(PrimitiveComponent(width=8.0, height=1.0, fill=(1, 1, 1)))
    toon.add_component(MaterialComponent(mode="toon", ambient_response=0.0, toon_steps=3))
    for y in (2.0, -2.0):
        light = scene.create_entity(f"light-{y}")
        light.add_component(TransformComponent(y=y))
        light.add_component(Light2DComponent(color=(1.0, 1.0, 1.0), radius=4.0))

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))

    smooth_values = {surface.get_at((x, 30)).r for x in range(15, 86)}
    toon_values = {surface.get_at((x, 70)).r for x in range(15, 86)}
    assert len(toon_values) < len(smooth_values)


def test_screen_capture_observes_lit_pixels_at_its_original_render_order() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("ordered capture")
    visual = scene.create_entity("lit visual")
    visual.add_component(PrimitiveComponent(width=1.0, height=1.0, fill=(1, 1, 1)))
    visual.add_component(MaterialComponent(ambient_response=0.0))
    light = scene.create_entity("light")
    light.add_component(Light2DComponent(color=(1.0, 0.0, 0.0), radius=3.0))
    capture = scene.create_entity("capture")
    capture.add_component(
        BackBufferCopyComponent(copy_mode="viewport", capture_id="lit-before-capture")
    )

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))

    snapshot = renderer._screen_pipeline.snapshot("lit-before-capture")
    assert snapshot is not None
    pixel = snapshot.base.get_at((50, 50))
    assert pixel.r > 100 and pixel.g < 20 and pixel.b < 20


def test_material_response_tracks_moving_lights_and_camera_zoom() -> None:
    import pygame

    pygame.font.init()
    scene = Scene("moving material light")
    visual = scene.create_entity("wide lit surface")
    visual.add_component(PrimitiveComponent(width=10.0, height=2.0, fill=(1, 1, 1)))
    visual.add_component(MaterialComponent(ambient_response=0.0))
    light = scene.create_entity("moving light")
    transform = TransformComponent()
    light.add_component(transform)
    light_component = Light2DComponent(color=(1.0, 0.5, 0.1), radius=1.0)
    light.add_component(light_component)

    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))
    center_brightness = surface.get_at((50, 50)).r

    transform.x = 3.0
    renderer.render(extract_render_frame(scene))
    assert surface.get_at((50, 50)).r < center_brightness
    assert surface.get_at((80, 50)).r > 0

    transform.x = 0.0
    light_component.radius = 2.0
    renderer.render(extract_render_frame(scene))
    assert surface.get_at((85, 50)).r == 0
    context = renderer.context
    assert context is not None
    context.camera.zoom = 2.0
    renderer.render(extract_render_frame(scene))
    assert surface.get_at((85, 50)).r > 0
    context.camera.position = (1.0, 0.0)
    renderer.render(extract_render_frame(scene))
    assert surface.get_at((30, 50)).r > surface.get_at((50, 50)).r


def test_material_response_visual_acceptance_frame(tmp_path) -> None:
    import pygame

    pygame.font.init()
    scene = Scene("material response visual acceptance")
    textures = {}
    floor = pygame.Surface((360, 203))
    floor.fill((35, 43, 60))
    for offset in range(-360, 720, 24):
        pygame.draw.line(floor, (49, 58, 76), (offset, 0), (offset + 203, 203), 1)
        pygame.draw.line(floor, (49, 58, 76), (offset, 203), (offset + 203, 0), 1)
    textures["assets://acceptance/isometric-floor"] = floor
    floor_entity = scene.create_entity("isometric floor", layer=-10)
    floor_entity.add_component(
        SpriteComponent("assets://acceptance/isometric-floor", width=24.0, height=13.5)
    )
    actor_colors = (
        (1, "lit", (-6.0, 0.0), (0.9, 0.75, 0.5), MaterialComponent(ambient_response=0.6)),
        (2, "unlit", (-2.0, 0.0), (0.2, 0.9, 1.0), MaterialComponent(mode="unlit")),
        (
            3,
            "emissive",
            (2.0, 0.0),
            (0.7, 0.2, 0.5),
            MaterialComponent(
                ambient_response=0.2,
                diffuse=0.4,
                emission=0.9,
                emission_color=(1.0, 0.15, 0.45),
            ),
        ),
        (
            4,
            "toon",
            (6.0, 0.0),
            (0.75, 0.78, 0.95),
            MaterialComponent(mode="toon", ambient_response=0.55, diffuse=1.0, toon_steps=3),
        ),
    )
    for _token, name, (x, y), color, material in actor_colors:
        texture = pygame.Surface((48, 64), pygame.SRCALPHA, 32)
        pygame.draw.ellipse(texture, (12, 15, 24, 120), (3, 48, 42, 13))
        pygame.draw.polygon(
            texture,
            (*[round(channel * 255) for channel in color], 255),
            ((24, 2), (43, 22), (36, 54), (12, 54), (5, 22)),
        )
        pygame.draw.line(texture, (240, 228, 194, 255), (15, 23), (33, 23), 3)
        asset = f"assets://acceptance/{name}"
        textures[asset] = texture
        entity = scene.create_entity(name)
        entity.add_component(TransformComponent(x=x, y=y))
        entity.add_component(SpriteComponent(asset, width=2.3, height=3.0))
        entity.add_component(material)

    scene.create_entity("ambient darkness").add_component(
        CanvasModulateComponent((0.18, 0.22, 0.34))
    )
    for name, position, color in (
        ("warm floor light", (-6.0, -1.2), (1.0, 0.42, 0.2)),
        ("cyan fill light", (-2.0, -1.0), (0.2, 0.72, 1.0)),
        ("torch light", (2.0, -0.8), (1.0, 0.4, 0.22)),
        ("cool toon light", (6.0, -0.8), (0.3, 0.52, 1.0)),
    ):
        light = scene.create_entity(name)
        light.add_component(TransformComponent(x=position[0], y=position[1]))
        light.add_component(Light2DComponent(color=color, radius=4.2, energy=0.9))

    surface = pygame.Surface((720, 405))
    renderer = PygameRenderer(
        pygame,
        surface,
        resource_provider=textures.__getitem__,
        clear_color=(15, 19, 29),
    )
    renderer.start(
        RenderContext(Viewport(0, 0, 720, 405), OrthographicCamera(width=24.0, height=13.5))
    )
    renderer.render(extract_render_frame(scene))
    pygame.image.save(surface, tmp_path / "material-response-acceptance.png")

    assert renderer.draw_failed is False
    assert surface.get_at((300, 202)).g > 150
    assert surface.get_at((540, 202)).r > 20
