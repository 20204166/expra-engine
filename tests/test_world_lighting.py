from __future__ import annotations

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.project import Project
from expra_engine.core.scene import Level, Scene, SceneInstanceComponent
from expra_engine.core.world import LevelDescriptor, World, WorldStreamingSettings
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.level_anchor import WorldPersistentActorComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.world_policy import StreamingAnchor
from expra_engine.runtime.world_streaming import WorldStreamingSystem
from tests.support.scheduling import ImmediateExecutor


def _level(name: str, ambient: tuple[float, float, float, float]) -> Level:
    level = Level(name, scene_id=name.lower())
    environment = level.create_entity(f"{name} environment", entity_id=f"{name}-environment")
    environment.add_component(CanvasModulateComponent(ambient))
    light = level.create_entity(f"{name} light", entity_id=f"{name}-light")
    light.add_component(
        component_from_dict(
            {
                "type": "light_2d",
                "kind": "point",
                "color": [1.0, 0.8, 0.6, 1.0],
                "energy": 1.0,
                "radius": 2.0,
                "falloff": 2.0,
            }
        )
    )
    return level


def test_world_lights_follow_active_content_and_ambient_uses_camera_level() -> None:
    town = _level("Town", (0.25, 0.15, 0.1, 1.0))
    forest = _level("Forest", (0.1, 0.2, 0.35, 1.0))
    courier = town.create_entity("Persistent Courier", entity_id="courier")
    courier.add_component(TransformComponent(x=50.0, y=50.0))
    courier.add_component(WorldPersistentActorComponent("courier"))
    torch = town.create_entity("Courier Torch", entity_id="courier-torch", parent_id="courier")
    torch.add_component(TransformComponent(x=1.0))
    torch.add_component(
        component_from_dict(
            {
                "type": "light_2d",
                "kind": "point",
                "color": [1.0, 0.7, 0.4, 1.0],
                "energy": 1.0,
                "radius": 2.0,
                "falloff": 2.0,
            }
        )
    )
    world = World(
        "World Lighting",
        world_id="world-lighting",
        levels=(
            LevelDescriptor(
                "town", "levels/town.level.pb", bounds=(0.0, 0.0, 100.0, 100.0)
            ),
            LevelDescriptor(
                "forest", "levels/forest.level.pb", origin=(100.0, 0.0),
                bounds=(100.0, 0.0, 100.0, 100.0),
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2),
    )
    system = WorldStreamingSystem(
        None,
        world,
        loader=lambda descriptor: {"town": town, "forest": forest}[descriptor.instance_id],
        executor_factory=lambda _workers: ImmediateExecutor(),
    )
    system.start(object())
    try:
        system.register_anchor(StreamingAnchor("party", "town", (50.0, 50.0)))
        initial = extract_render_frame(
            system.runtime_scene,
            modulation_entity_ids=system.environment_entity_ids,
        )
        assert len(initial.lights) == 2
        assert all(
            light.entity_id in system.environment_entity_ids
            for light in initial.lights
            if light.position != (51.0, 50.0, 0.0)
        )
        persistent_light = next(light for light in initial.lights if light.position == (51.0, 50.0, 0.0))
        assert persistent_light.entity_id not in system.environment_entity_ids
        assert initial.modulation == Color(0.25, 0.15, 0.1, 1.0)

        system.request_load("forest")
        system.update()
        assert system.activate_level("forest") is True
        overlapping = extract_render_frame(
            system.runtime_scene,
            modulation_entity_ids=system.environment_entity_ids,
        )

        assert len(overlapping.lights) == 3
        assert overlapping.modulation == Color(0.25, 0.15, 0.1, 1.0)
        assert next(light for light in overlapping.lights if light.entity_id == persistent_light.entity_id).position == (51.0, 50.0, 0.0)

        system.unregister_anchor("party")
        system.register_anchor(StreamingAnchor("party", "forest", (150.0, 50.0)))
        system.report_camera_view((150.0, 50.0), (10.0, 10.0))
        forest_context = extract_render_frame(
            system.runtime_scene,
            modulation_entity_ids=system.environment_entity_ids,
        )
        assert len(forest_context.lights) == 3
        assert forest_context.modulation == Color(0.1, 0.2, 0.35, 1.0)
        assert next(light for light in forest_context.lights if light.entity_id == persistent_light.entity_id).position == (51.0, 50.0, 0.0)
        assert system.deactivate_level("town") is True
        assert system.unload_level("town") is True
        after_unload = extract_render_frame(system.runtime_scene)
        assert any(light.entity_id == persistent_light.entity_id for light in after_unload.lights)
    finally:
        system.close()


def test_scene_instance_light_survives_canonical_pb_round_trip_and_world_placement(
    tmp_path,
) -> None:
    project = Project.create("Lamp Scene", tmp_path / "project")
    lamp = Scene("Reusable Lamp", scene_id="lamp")
    light = lamp.create_entity("Lamp Light", entity_id="lamp-light")
    light.add_component(TransformComponent(x=2.0, y=3.0))
    light.add_component(
        component_from_dict(
            {
                "type": "light_2d",
                "kind": "point",
                "color": [1.0, 0.8, 0.5, 1.0],
                "energy": 1.0,
                "radius": 2.0,
                "falloff": 2.0,
            }
        )
    )
    project.save_document(lamp, "scenes/lamp.scene.pb")
    level = Level("Town", scene_id="town")
    instance = level.create_entity("Street Lamp", entity_id="street-lamp")
    instance.add_component(TransformComponent(x=5.0))
    instance.add_component(SceneInstanceComponent("scenes/lamp.scene.pb"))
    project.save_document(level, "levels/town.level.pb")

    world = World(
        "Lamp World",
        world_id="lamp-world",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb", origin=(100.0, 50.0)),
        ),
        initial_level_id="town",
    )
    system = WorldStreamingSystem(
        project,
        world,
        executor_factory=lambda _workers: ImmediateExecutor(),
    )
    system.start(object())
    try:
        frame = extract_render_frame(system.runtime_scene)
        assert len(frame.lights) == 1
        assert frame.lights[0].position == (107.0, 53.0, 0.0)
    finally:
        system.close()
