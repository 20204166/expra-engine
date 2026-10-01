"""World streaming state-machine and bounded residency tests."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World, WorldStreamingSettings
from expra_engine.runtime.audio_2d import (
    Audio2DWorld,
    AudioListener2DComponent,
    AudioStreamPlayer2DComponent,
)
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.physics_world import PhysicsWorld2D
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import OrthographicCamera
from expra_engine.runtime.runtime_camera import RuntimeCameraResolver
from expra_engine.runtime.visual_components import PrimitiveComponent
from tests.support.pixel_surface import color_bounds
from tests.support.scheduling import ManualExecutor


def test_world_streaming_has_one_runtime_owner_module() -> None:
    assert importlib.util.find_spec("expra_engine.runtime.world_streaming") is not None


def test_world_runtime_owner_exposes_the_bounded_system() -> None:
    from importlib import import_module

    module = import_module("expra_engine.runtime.world_streaming")
    assert hasattr(module, "WorldStreamingSystem")


def test_world_streaming_policy_has_an_explicit_decision_surface() -> None:
    from importlib import import_module

    module = import_module("expra_engine.runtime.world_streaming")
    assert all(
        hasattr(module, name)
        for name in ("StreamingAnchor", "StreamingDecision", "WorldStreamingPolicy")
    )


def _residency_types():
    from expra_engine.runtime.world_streaming import (
        LevelResidencyManager,
        LevelResidencyState,
        ResidencyCapacityError,
        WorldStreamingSystem,
    )

    return LevelResidencyManager, LevelResidencyState, ResidencyCapacityError, WorldStreamingSystem


def _streaming_world() -> World:
    return World(
        "World",
        world_id="world",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", priority=5),
            LevelDescriptor("city", "levels/city.level.pb", priority=1),
        ),
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=3),
    )


def _policy_world(*, budget: int = 3) -> World:
    from expra_engine.core.world import WorldConnection

    return World(
        "Connected",
        world_id="connected",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb"),
            LevelDescriptor("city", "levels/city.level.pb"),
        ),
        connections=(
            WorldConnection(
                "town-forest", "town", "east", "forest", "west",
                preload_distance=10.0, unload_distance=20.0,
            ),
            WorldConnection(
                "forest-city", "forest", "north", "city", "south",
                preload_distance=10.0, unload_distance=20.0,
            ),
        ),
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=2, max_loaded_levels=budget),
    )


def _seamless_world() -> World:
    from expra_engine.core.world import WorldConnection

    return World(
        "Seamless",
        world_id="seamless",
        levels=(
            LevelDescriptor(
                "town", "levels/town.level.pb", origin=(0.0, 0.0), bounds=(0.0, 0.0, 100.0, 100.0)
            ),
            LevelDescriptor(
                "forest", "levels/forest.level.pb", origin=(100.0, 0.0), bounds=(100.0, 0.0, 100.0, 100.0)
            ),
        ),
        connections=(
            WorldConnection(
                "town-forest",
                "town",
                "east",
                "forest",
                "west",
                bidirectional=True,
                preload_distance=20.0,
                unload_distance=40.0,
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=2, max_loaded_levels=2),
    )


def test_stale_completion_cannot_overwrite_a_retried_level_request() -> None:
    Manager, State, _CapacityError, _System = _residency_types()
    manager = Manager(("town",), max_resident_levels=1)
    first = manager.request_load("town")
    assert manager.begin_load("town", first)
    manager.cancel_load("town")
    second = manager.request_load("town")
    assert second > first
    assert manager.begin_load("town", second)

    assert not manager.complete_load("town", first, Level("stale"))
    assert manager.state("town").state is State.LOADING
    assert manager.state("town").generation == second
    assert manager.complete_load("town", second, Level("current"))
    assert manager.state("town").state is State.LOADED
    assert manager.state("town").level_name == "current"


def test_residency_snapshot_reports_metadata_without_exposing_mutable_level_graph() -> None:
    Manager, _State, _CapacityError, _System = _residency_types()
    manager = Manager(("town",))
    generation = manager.request_load("town")
    manager.begin_load("town", generation)
    manager.complete_load("town", generation, Level("Town"))

    snapshot = manager.state("town")

    assert snapshot.has_level
    assert snapshot.level_name == "Town"
    assert not hasattr(snapshot, "level")


def test_only_loaded_levels_can_activate_and_inactive_residency_is_reused() -> None:
    Manager, State, _CapacityError, _System = _residency_types()
    manager = Manager(("town",))

    assert not manager.activate("town")
    generation = manager.request_load("town")
    assert manager.begin_load("town", generation)
    assert manager.complete_load("town", generation, Level("Town"))
    assert manager.activate("town")
    assert manager.state("town").state is State.ACTIVE
    assert manager.deactivate("town")
    assert manager.state("town").state is State.DORMANT
    assert manager.activate("town")
    assert manager.state("town").state is State.ACTIVE


def test_resident_level_budget_bounds_pending_and_loaded_requests() -> None:
    Manager, State, CapacityError, _System = _residency_types()
    manager = Manager(("one", "two", "three"), max_resident_levels=2)
    first = manager.request_load("one")
    manager.request_load("two")
    assert manager.state("one").state is State.QUEUED
    assert manager.state("two").state is State.QUEUED

    with pytest.raises(CapacityError):
        manager.request_load("three")

    manager.cancel_load("two")
    assert manager.request_load("three") == 1
    assert manager.state("three").state is State.QUEUED
    assert manager.state("two").state is State.CANCELLED
    assert manager.state("one").generation == first


def test_failed_load_has_bounded_error_and_explicit_retry() -> None:
    Manager, State, _CapacityError, _System = _residency_types()
    manager = Manager(("town",))
    generation = manager.request_load("town")
    assert manager.begin_load("town", generation)

    assert manager.fail_load("town", generation, RuntimeError("x" * 500))
    failed = manager.state("town")
    assert failed.state is State.FAILED
    assert failed.error is not None and len(failed.error) <= 200
    retry = manager.request_load("town")
    assert retry > generation
    assert manager.state("town").state is State.QUEUED


def test_failed_activation_is_not_published_and_requires_explicit_retry() -> None:
    Manager, State, _CapacityError, _System = _residency_types()
    manager = Manager(("town",))
    generation = manager.request_load("town")
    assert manager.begin_load("town", generation)
    assert manager.complete_load("town", generation, Level("Town"))

    assert manager.fail_activation("town", RuntimeError("behaviour start failed"))

    failed = manager.state("town")
    assert failed.state is State.FAILED
    assert not failed.has_level
    assert "behaviour start failed" in failed.error
    assert manager.request_load("town") > generation


def test_world_streaming_settings_are_used_as_a_hard_budget() -> None:
    settings = WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2)
    world = World(
        "Town",
        world_id="town",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
        streaming=settings,
    )

    assert world.streaming.max_loaded_levels == 2
    with pytest.raises(ValueError):
        WorldStreamingSettings(max_concurrent_loads=True)  # type: ignore[arg-type]


def test_level_loads_are_bounded_and_priority_is_deterministic() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    system = System(
        None,
        _streaming_world(),
        loader=lambda descriptor: Level(descriptor.instance_id),
        executor_factory=lambda max_workers: executor,
    )
    system.start(object())
    system.request_load("forest")
    system.request_load("city")

    assert len(executor.jobs) == 1
    assert system.state("town").state is State.LOADING
    executor.complete()
    assert system.state("town").state is State.LOADING
    system.update()
    assert system.state("town").state is State.ACTIVE, system.snapshot()
    assert len(executor.jobs) == 2
    executor.complete(1)
    system.update()
    assert system.state("forest").level_name == "forest"
    assert len(executor.jobs) == 3
    executor.complete(2)
    system.update()
    assert system.state("city").level_name == "city"
    system.stop()


def test_running_cancelled_load_finishes_stale_then_retry_loads() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    system = System(
        None,
        _streaming_world(),
        loader=lambda descriptor: Level(f"loaded:{descriptor.instance_id}"),
        executor_factory=lambda max_workers: executor,
    )
    system.start(object())
    stale_generation = system.state("town").generation
    future = executor.jobs[0][0]
    assert future.set_running_or_notify_cancel()

    assert system.cancel_load("town")
    retry_generation = system.request_load("town")
    assert retry_generation > stale_generation
    executor.complete()
    system.update()

    assert system.state("town").state is State.LOADING
    assert system.state("town").generation == retry_generation
    assert system.snapshot().stale_results_discarded == 1
    executor.complete(1)
    system.update()
    assert system.state("town").level_name == "loaded:town"
    system.stop()


def test_policy_preloads_at_inclusive_distance_and_retains_to_hysteresis_edge() -> None:
    from expra_engine.runtime.world_streaming import StreamingAnchor, WorldStreamingPolicy

    world = _policy_world()
    policy = WorldStreamingPolicy()
    anchors = (StreamingAnchor("party", "town", (10.0, 0.0)),)
    exits = {("town", "east"): (0.0, 0.0)}

    decision = policy.decide(world, anchors, exits, initial_level_id="town")

    assert decision.active_level_ids == ("town",)
    assert decision.resident_level_ids == ("forest", "town")
    assert decision.preload_level_ids == ("forest",)

    retained = policy.decide(
        world,
        (StreamingAnchor("party", "town", (20.0, 0.0)),),
        exits,
        resident_level_ids=("forest", "town"),
        initial_level_id="town",
    )
    assert retained.resident_level_ids == ("forest", "town")

    evicted = policy.decide(
        world,
        (StreamingAnchor("party", "town", (20.001, 0.0)),),
        exits,
        resident_level_ids=("forest", "town"),
        initial_level_id="town",
    )
    assert evicted.resident_level_ids == ("town",)


def test_policy_unions_multiple_anchors_and_fails_if_active_set_exceeds_budget() -> None:
    from expra_engine.runtime.world_streaming import (
        ResidencyCapacityError,
        StreamingAnchor,
        WorldStreamingPolicy,
    )

    world = _policy_world()
    decision = WorldStreamingPolicy().decide(
        world,
        (
            StreamingAnchor("party-a", "town", (100.0, 100.0)),
            StreamingAnchor("party-b", "forest", (100.0, 100.0)),
        ),
        {},
        initial_level_id=None,
    )
    assert decision.active_level_ids == ("forest", "town")
    assert decision.resident_level_ids == ("forest", "town")

    tiny_world = _policy_world(budget=1)
    with pytest.raises(ResidencyCapacityError):
            WorldStreamingPolicy().decide(
            tiny_world,
            (
                StreamingAnchor("party-a", "town", (0.0, 0.0)),
                StreamingAnchor("party-b", "forest", (0.0, 0.0)),
            ),
            {},
        )


def test_active_level_entities_use_world_origin_and_can_be_dormant_without_recreation() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    authored = Level("Town", scene_id="town-document")
    hero = authored.create_entity("Courier", entity_id="hero")
    hero.add_component(TransformComponent(x=2.0, y=3.0))
    world = World(
        "World",
        world_id="world",
        levels=(LevelDescriptor("town", "levels/town.level.pb", origin=(100.0, 50.0)),),
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda max_workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()

    assert system.state("town").state is State.ACTIVE
    runtime_hero = next(entity for entity in system.runtime_scene.entities if entity.name == "Courier")
    assert runtime_hero.entity_id != hero.entity_id
    assert system.runtime_scene.world_pose(runtime_hero.entity_id)[:2] == (102.0, 53.0)
    assert authored.find_entity("hero") is hero

    assert system.deactivate_level("town")
    assert system.runtime_scene.find_entity(runtime_hero.entity_id) is None
    assert system.state("town").state is State.DORMANT
    assert system.activate_level("town")
    assert system.runtime_scene.find_entity(runtime_hero.entity_id) is runtime_hero
    system.close()


def test_streaming_anchor_components_resolve_through_canonical_world_pose() -> None:
    from expra_engine.runtime.level_anchor import StreamingAnchorComponent

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    authored = Level("Town")
    actor = authored.create_entity("Party Leader", entity_id="leader")
    actor.add_component(TransformComponent(x=12.0, y=3.0))
    actor.add_component(StreamingAnchorComponent("party"))
    world = World(
        "World",
        world_id="world",
        levels=(LevelDescriptor("town", "levels/town.level.pb", origin=(2000.0, 40.0)),),
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()

    anchors = system.streaming_anchors()

    assert [(item.anchor_id, item.level_id, item.position) for item in anchors] == [
        ("party", "town", (2012.0, 43.0))
    ]
    system.close()


def test_streaming_anchor_scan_does_not_walk_every_active_world_entity() -> None:
    from unittest.mock import patch

    from expra_engine.core.scene import Scene
    from expra_engine.runtime.level_anchor import StreamingAnchorComponent

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    town = Level("Town")
    actor = town.create_entity("Party Leader")
    actor.add_component(TransformComponent())
    actor.add_component(StreamingAnchorComponent("party"))
    for index in range(40):
        town.create_entity(f"Decoration {index}").add_component(TransformComponent())
    system = System(
        None,
        World(
            "World",
            world_id="world",
            levels=(LevelDescriptor("town", "levels/town.level.pb"),),
            initial_level_id="town",
        ),
        loader=lambda _descriptor: town,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    original_entities = Scene.entities.fget

    def reject_aggregate_scan(scene):
        if scene is system.runtime_scene:
            raise AssertionError("streaming anchors scanned the complete World entity graph")
        return original_entities(scene)

    with patch.object(Scene, "entities", property(reject_aggregate_scan)):
        anchors = system.streaming_anchors()

    assert len(anchors) == 1
    assert anchors[0].anchor_id == "party"
    system.close()


def test_world_persistent_actor_survives_level_unload_and_source_reload() -> None:
    from expra_engine.runtime.level_anchor import WorldPersistentActorComponent

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)

    def load_level(descriptor):
        level = Level(descriptor.instance_id)
        if descriptor.instance_id == "town":
            actor = level.create_entity("Courier", entity_id="courier")
            actor.add_component(WorldPersistentActorComponent("main-courier"))
        return level

    world = World(
        "World",
        world_id="world",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb"),
        ),
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2),
    )
    system = System(
        None,
        world,
        loader=load_level,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    actor_before = next(
        entity
        for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )

    assert system.deactivate_level("town")
    assert system.unload_level("town")
    assert system.runtime_scene.find_entity(actor_before.entity_id) is actor_before
    assert system.state("town").state is State.UNLOADED

    system.request_load("town")
    system.update()
    executor.complete(1)
    system.update()
    actors = [
        entity
        for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    ]
    assert actors == [actor_before]
    system.close()


def test_level_deactivation_transfers_runtime_generated_descendants_with_owner() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)

    def load_level(descriptor):
        level = Level(descriptor.instance_id)
        if descriptor.instance_id == "town":
            level.create_entity("Isometric Test Floor", entity_id="floor")
        return level

    system = System(
        None,
        _streaming_world(),
        loader=load_level,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    assert system.state("town").state is State.ACTIVE

    floor = system.runtime_scene.find_entity_by_name("Isometric Test Floor")
    assert floor is not None
    generated = system.runtime_scene.create_entity("Floor Tile", parent_id=floor.entity_id)
    generated.add_component(TransformComponent())

    assert system.deactivate_level("town")

    dormant_level = system._runtime_levels["town"]
    assert dormant_level.find_entity(floor.entity_id) is floor
    assert dormant_level.find_entity(generated.entity_id) is generated
    assert system.runtime_scene.find_entity(floor.entity_id) is None
    assert system.state("town").state is State.DORMANT

    assert system.activate_level("town")
    assert system.runtime_scene.find_entity(generated.entity_id) is generated
    system.close()


def test_failed_level_deactivation_keeps_residency_active() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)

    def load_level(descriptor):
        level = Level(descriptor.instance_id)
        if descriptor.instance_id == "town":
            level.create_entity("Floor", entity_id="floor")
        return level

    system = System(
        None,
        _streaming_world(),
        loader=load_level,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    assert system.state("town").state is State.ACTIVE

    floor = system.runtime_scene.find_entity_by_name("Floor")
    assert floor is not None
    # Force the canonical transfer validator to reject before it moves anything.
    system._runtime_levels["town"].create_entity(
        "Duplicate floor ID", entity_id=floor.entity_id
    )

    with pytest.raises(ValueError, match="already contains Entity IDs"):
        system.deactivate_level("town")

    assert system.state("town").state is State.ACTIVE
    assert system.runtime_scene.find_entity(floor.entity_id) is floor
    system._runtime_levels["town"].remove_entity(floor.entity_id)
    system.close()


def test_cross_owner_persistent_actor_parenting_is_rejected_during_materialization() -> None:
    from expra_engine.runtime.level_anchor import WorldPersistentActorComponent
    from expra_engine.runtime.world_materialize import _materialize_world_level

    authored = Level("Town")
    parent = authored.create_entity("Group", entity_id="group")
    authored.create_entity(
        "Courier", entity_id="courier", parent_id=parent.entity_id
    ).add_component(WorldPersistentActorComponent("courier"))

    with pytest.raises(ValueError, match="Level root"):
        _materialize_world_level(
            authored,
            LevelDescriptor("town", "levels/town.level.pb"),
            world_id="world",
        )


def test_fresh_world_start_places_primary_actor_at_initial_entrance_in_world_space() -> None:
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        LevelAnchorKind,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(1)
    authored = Level("Town")
    parent = authored.create_entity("Entrance Group", entity_id="entrance-group")
    parent.add_component(TransformComponent(x=5.0, y=7.0))
    entrance = authored.create_entity(
        "Start Entrance", entity_id="start-entrance", parent_id=parent.entity_id
    )
    entrance.add_component(TransformComponent(x=2.0, y=-3.0))
    entrance.add_component(LevelAnchorComponent("start", kind=LevelAnchorKind.ENTRANCE))
    actor = authored.create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent(x=1.0, y=2.0))
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb", origin=(100.0, 200.0)),),
        primary_anchor_id="party",
        initial_level_id="town",
        initial_entrance_id="start",
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )

    system.start(object())
    executor.complete()
    system.update()

    runtime_actor = next(
        entity
        for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    transform = runtime_actor.get_component(TransformComponent)
    assert transform is not None
    assert (transform.x, transform.y) == (107.0, 204.0)
    assert system.current_level("party") == "town"
    assert system.state("town").state is _State.ACTIVE
    assert system.camera_context.follow_target_entity_id == runtime_actor.entity_id
    # Runtime bootstrap must not move the authored actor or entrance.
    assert (
        authored.find_entity("courier").get_component(TransformComponent).x,
        authored.find_entity("courier").get_component(TransformComponent).y,
    ) == (1.0, 2.0)
    system.close()


def test_world_without_initial_entrance_starts_at_authored_primary_actor_position() -> None:
    from expra_engine.runtime.level_anchor import (
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(1)
    authored = Level("Town")
    actor = authored.create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent(x=3.0, y=4.0))
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    system = System(
        None,
        World(
            "Main",
            world_id="main",
            levels=(LevelDescriptor("town", "levels/town.level.pb"),),
            initial_level_id="town",
            primary_anchor_id="party",
            initial_entrance_id=None,
        ),
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )

    system.start(object())
    executor.complete()
    system.update()

    runtime_actor = next(
        entity
        for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    transform = runtime_actor.get_component(TransformComponent)
    assert transform is not None
    assert (transform.x, transform.y) == (3.0, 4.0)
    assert system.state("town").state is State.ACTIVE
    system.close()


def test_configured_missing_primary_anchor_keeps_initial_level_active_and_reports_error() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(1)
    authored = Level("Town")
    authored.create_entity("Visible Level Content")
    system = System(
        None,
        World(
            "Main",
            world_id="main",
            levels=(LevelDescriptor("town", "levels/town.level.pb"),),
            initial_level_id="town",
            primary_anchor_id="missing-player",
        ),
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )

    system.start(object())
    executor.complete()
    system.update()

    assert system.state("town").state is State.ACTIVE
    assert any(entity.name == "Visible Level Content" for entity in system.runtime_scene.entities)
    assert system.snapshot().last_transition_error == (
        "World primary anchor 'missing-player' is not present in the active startup Level "
        "'town'; the Level remains active for rendering"
    )
    system.close()


def test_configured_primary_anchor_without_persistent_actor_is_nonfatal_but_reported() -> None:
    from expra_engine.runtime.level_anchor import StreamingAnchorComponent

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(1)
    authored = Level("Town")
    actor = authored.create_entity("Temporary Anchor")
    actor.add_component(StreamingAnchorComponent("player"))
    system = System(
        None,
        World(
            "Main",
            world_id="main",
            levels=(LevelDescriptor("town", "levels/town.level.pb"),),
            initial_level_id="town",
            primary_anchor_id="player",
        ),
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )

    system.start(object())
    executor.complete()
    system.update()

    assert system.state("town").state is State.ACTIVE
    assert system.current_level("player") == "town"
    assert system.snapshot().last_transition_error == (
        "World primary anchor 'player' is not attached to an active "
        "World-persistent actor; the Level remains active for rendering"
    )
    system.close()


def test_missing_initial_entrance_fails_initial_level_with_specific_error() -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(1)
    authored = Level("Town")
    authored.create_entity("Visible Level Content")
    system = System(
        None,
        World(
            "Main",
            world_id="main",
            levels=(LevelDescriptor("town", "levels/town.level.pb"),),
            initial_level_id="town",
            initial_entrance_id="missing-entry",
        ),
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )

    system.start(object())
    executor.complete()
    system.update()

    startup = system.state("town")
    assert startup.state is State.FAILED
    assert startup.error == (
        "ValueError: World initial entrance 'missing-entry' is not an entrance anchor "
        "in Level 'town'"
    )
    assert system.startup_error == (
        "World startup Level 'town' failed to load: ValueError: "
        "World initial entrance 'missing-entry' is not an entrance anchor in Level 'town'"
    )
    assert system.runtime_scene.entities == ()
    system.close()


def test_world_camera_context_keeps_previous_bounds_until_camera_enters_new_level() -> None:
    from expra_engine.runtime.world_streaming import StreamingAnchor

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    world = World(
        "Camera World",
        world_id="camera-world",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb", bounds=(0.0, 0.0, 100.0, 100.0)),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0), bounds=(100.0, 0.0, 100.0, 100.0)),
        ),
        primary_anchor_id="camera-anchor",
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: Level(descriptor.instance_id),
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    system.request_load("forest")
    executor.complete(1)
    system.update()
    system.activate_level("forest")
    system.register_anchor(StreamingAnchor("camera-anchor", "town", (90.0, 50.0)))

    assert system.camera_context.camera_context_level_id == "town"
    assert system.camera_context.effective_bounds == (0.0, 0.0, 200.0, 100.0)
    system.report_camera_view((90.0, 50.0), (20.0, 10.0))
    assert system.camera_context.camera_context_level_id == "town"
    system.register_anchor(StreamingAnchor("camera-anchor", "forest", (115.0, 50.0)))
    system.report_camera_view((115.0, 50.0), (20.0, 10.0))
    assert system.camera_context.camera_context_level_id == "forest"

    system.deactivate_level("town")
    assert system.camera_context.effective_bounds == (100.0, 0.0, 200.0, 100.0)
    assert system.state("forest").state is State.ACTIVE
    system.close()


def test_unload_captures_opted_in_session_state_and_reload_restores_it() -> None:
    from expra_engine.runtime.world_state import WorldSessionStateComponent

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    authored: dict[str, Level] = {}
    start = Level("Start")
    town = Level("Town")
    door = town.create_entity("Door", entity_id="door")
    door.add_component(WorldSessionStateComponent({"open": False, "uses_left": 2}))
    authored.update(start=start, town=town)
    world = World(
        "Session World",
        world_id="session-world",
        levels=(
            LevelDescriptor("start", "levels/start.level.pb"),
            LevelDescriptor("town", "levels/town.level.pb"),
        ),
        initial_level_id="start",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2),
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    system.request_load("town")
    executor.complete(1)
    system.update()
    assert system.activate_level("town")
    runtime_door = next(entity for entity in system.runtime_scene.entities if entity.name == "Door")
    runtime_state = runtime_door.get_component(WorldSessionStateComponent)
    assert runtime_state is not None
    runtime_state.values["open"] = True

    assert system.deactivate_level("town")
    assert system.unload_level("town")
    assert authored["town"].find_entity("door").get_component(
        WorldSessionStateComponent
    ).values["open"] is False

    system.request_load("town")
    executor.complete(2)
    system.update()
    assert system.state("town").state is State.LOADED
    assert system.activate_level("town")
    restored = next(entity for entity in system.runtime_scene.entities if entity.name == "Door")
    restored_state = restored.get_component(WorldSessionStateComponent)
    assert restored_state is not None
    assert restored_state.values == {"open": True, "uses_left": 2}
    system.stop()
    assert system.session_state["levels"] == {}
    system.close()


def test_session_capture_failure_keeps_level_resident_and_recoverable() -> None:
    from expra_engine.runtime.world_state import WorldSessionStateComponent

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    town = Level("Town")
    door = town.create_entity("Door")
    door.add_component(WorldSessionStateComponent({"open": False}))
    world = World(
        "Capture Failure",
        world_id="capture-failure",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: town,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    runtime_door = next(entity for entity in system.runtime_scene.entities if entity.name == "Door")
    runtime_door.get_component(WorldSessionStateComponent).values["unsupported"] = object()

    assert not system.unload_level("town")
    assert system.state("town").state is State.DORMANT
    assert system.state("town").has_level
    assert "capture" in (system.snapshot().last_session_error or "")
    system.close()


def test_authored_entity_deletion_survives_world_level_unload_and_reload() -> None:
    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    authored = Level("Town")
    authored.create_entity("Enemy", entity_id="enemy")
    world = World(
        "Deletion Session",
        world_id="deletion-session",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    enemy = next(entity for entity in system.runtime_scene.entities if entity.name == "Enemy")
    system.runtime_scene.remove_entity(enemy.entity_id, recursive=True)

    assert system.deactivate_level("town")
    assert system.unload_level("town")
    assert system.session_state["deleted_entities"]["town"]
    system.request_load("town")
    executor.complete(1)
    system.update()

    assert not any(entity.name == "Enemy" for entity in system.runtime_scene.entities)
    assert authored.find_entity("enemy") is not None
    system.close()


def test_declared_seamless_connection_preloads_hands_over_and_unloads_without_actor_reset() -> None:
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    authored: dict[str, Level] = {}
    town = Level("Town", scene_id="town-source")
    actor = town.create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent(x=0.0, y=0.0))
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    actor.add_component(ColliderComponent(width=2.0, height=2.0))
    actor.add_component(AudioListener2DComponent(current=True))
    gate = town.create_entity("East Gate", entity_id="east-gate")
    gate.add_component(TransformComponent(x=100.0, y=0.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    gate.add_component(ColliderComponent(width=4.0, height=4.0))
    gate.add_component(PrimitiveComponent("rectangle", width=4.0, height=4.0))
    forest = Level("Forest", scene_id="forest-source")
    entry = forest.create_entity("West Entry", entity_id="west-entry")
    entry.add_component(TransformComponent(x=0.0, y=0.0))
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    entry.add_component(ColliderComponent(width=4.0, height=4.0))
    entry.add_component(AudioStreamPlayer2DComponent("forest.ogg", max_distance=100.0))
    entry.add_component(PrimitiveComponent("rectangle", width=4.0, height=4.0))
    authored.update(town=town, forest=forest)
    system = System(
        None,
        _seamless_world(),
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    camera = OrthographicCamera(width=10.0, height=10.0)
    camera_engine = SimpleNamespace(
        active_scene=system.runtime_scene,
        world_streaming_system=system,
    )
    camera_resolver = RuntimeCameraResolver(camera)
    camera_resolver.sync(camera_engine)
    camera.zoom = 1.5
    camera.rotation = 0.25
    camera.position_smoothing_enabled = True
    actor_before = next(
        item
        for item in system.runtime_scene.entities
        if item.get_component(WorldPersistentActorComponent) is not None
    )
    assert system.state("forest").state is State.UNLOADED

    actor_before.get_component(TransformComponent).x = 90.0
    system.update()
    assert system.state("forest").state is State.LOADING
    executor.complete(1)
    system.update()
    assert system.state("forest").state is State.LOADED

    actor_before.get_component(TransformComponent).x = 99.0
    system.update()
    assert system.state("forest").state is State.ACTIVE
    assert system.state("town").state is State.ACTIVE
    system.update()
    system.update()
    assert system.state("town").state is State.DORMANT
    assert system.runtime_scene.find_entity(actor_before.entity_id) is actor_before
    assert system.runtime_scene.world_pose(actor_before.entity_id)[0] == 99.0
    assert system.current_level("party") == "forest"
    forest_entry = next(
        entity for entity in system.runtime_scene.entities if entity.name == "West Entry"
    )
    assert forest_entry.entity_id in PhysicsWorld2D(system.runtime_scene).overlap(
        actor_before.entity_id
    )
    frame = extract_render_frame(system.runtime_scene)
    forest_item = next(item for item in frame.items if item.key == forest_entry.entity_id)
    assert forest_item.world_transform.position[:2] == (100.0, 0.0)
    assert Audio2DWorld(system.runtime_scene).mix_for(
        forest_entry.entity_id, viewport_width=100.0
    ).distance == 1.0
    camera_resolver.sync(camera_engine)
    assert camera_resolver.camera is camera
    assert camera.target_position == (99.0, 0.0)
    assert camera.zoom == 1.5
    assert camera.rotation == 0.25
    assert camera.position_smoothing_enabled
    assert (camera.limit_left, camera.limit_bottom, camera.limit_right, camera.limit_top) == (
        0.0, 0.0, 200.0, 100.0
    )

    actor_before.get_component(TransformComponent).x = 141.0
    system.update()
    assert system.state("town").state is State.UNLOADED
    assert system.runtime_scene.find_entity(actor_before.entity_id) is actor_before
    assert authored["town"].find_entity("courier").get_component(TransformComponent).x == 0.0
    camera.position = (150.0, 50.0)
    system.report_camera_view(camera.position[:2], (camera.width, camera.height))
    camera_resolver.sync(camera_engine)
    assert camera_resolver.camera is camera
    assert camera.rotation == 0.25
    assert camera.zoom == 1.5
    assert (camera.limit_left, camera.limit_bottom, camera.limit_right, camera.limit_top) == (
        100.0, 0.0, 200.0, 100.0
    )

    actor_before.get_component(TransformComponent).x = 101.0
    system.update()
    assert system.state("town").state is State.LOADING
    assert actor_before.get_component(TransformComponent).x == 100.0
    executor.complete(2)
    system.update()
    assert system.state("town").state is State.ACTIVE, system.snapshot()
    assert system.current_level("party") == "town"
    assert system.runtime_scene.find_entity(actor_before.entity_id) is actor_before
    assert system.runtime_scene.world_pose(actor_before.entity_id)[0] == 100.0
    system.close()


def test_high_speed_actor_crossing_exit_trigger_transitions_without_teleport() -> None:
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent())
    courier.add_component(WorldPersistentActorComponent("courier"))
    courier.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    authored = {"town": town, "forest": forest}
    system = System(
        None,
        _seamless_world(),
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    runtime_courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )

    runtime_courier.get_component(TransformComponent).x = 90.0
    system.update()
    executor.complete(1)
    system.update()
    assert system.state("forest").state is State.LOADED

    runtime_courier.get_component(TransformComponent).x = 110.0
    system.update()

    assert system.current_level("party") == "forest"
    assert system.runtime_scene.find_entity(runtime_courier.entity_id) is runtime_courier
    assert system.runtime_scene.world_pose(runtime_courier.entity_id)[0] == 110.0
    assert system.state("forest").state is State.ACTIVE
    system.close()


def test_instant_connection_moves_persistent_actor_to_named_destination_anchor() -> None:
    from dataclasses import replace

    from expra_engine.core.world import TransitionMode
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent())
    courier.add_component(WorldPersistentActorComponent("courier"))
    courier.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    world = _seamless_world()
    world = replace(
        world,
        connections=(replace(world.connections[0], transition=TransitionMode.INSTANT),),
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: town if descriptor.instance_id == "town" else forest,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    runtime_courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    runtime_courier.get_component(TransformComponent).x = 90.0
    system.update()
    executor.complete(1)
    system.update()
    runtime_courier.get_component(TransformComponent).x = 99.0
    system.update()

    assert system.current_level("party") == "forest"
    assert system.runtime_scene.world_pose(runtime_courier.entity_id)[0] == 100.0
    assert system.transition.mode is TransitionMode.INSTANT
    assert system.transition.status.value == "complete"
    assert system.camera_context.camera_context_level_id == "forest"
    assert system.camera_context.recenter_generation == 1
    system.close()


def test_fade_connection_waits_for_destination_then_commits_between_fades() -> None:
    from dataclasses import replace

    from expra_engine.core.world import TransitionMode
    from expra_engine.runtime.events import FrameUpdate
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )
    from expra_engine.runtime.world_transition import TransitionStatus

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent())
    courier.add_component(WorldPersistentActorComponent("courier"))
    courier.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    world = _seamless_world()
    world = replace(
        world,
        connections=(replace(world.connections[0], transition=TransitionMode.FADE),),
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: town if descriptor.instance_id == "town" else forest,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    player = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    player.get_component(TransformComponent).x = 90.0
    system.update()
    executor.complete(1)
    system.update()
    player.get_component(TransformComponent).x = 99.0
    system.update()

    assert system.transition.status is TransitionStatus.FADING_OUT
    assert system.transition.alpha == 0.0
    assert system.current_level("party") == "town"
    system.on_frame_update(FrameUpdate(0.1), None)
    assert system.transition.status is TransitionStatus.FADING_OUT
    assert system.transition.alpha == 0.5
    system.on_frame_update(FrameUpdate(0.1), None)
    assert system.transition.status is TransitionStatus.FADING_IN
    assert system.transition.alpha == 1.0
    assert system.current_level("party") == "forest"
    system.on_frame_update(FrameUpdate(0.2), None)
    assert system.transition.status is TransitionStatus.COMPLETE
    assert system.transition.alpha == 0.0
    system.close()


def test_manual_fade_travel_uses_the_same_loader_without_moving_actor_while_preparing() -> None:
    from dataclasses import replace

    from expra_engine.core.world import TransitionMode
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )
    from expra_engine.runtime.world_transition import TransitionStatus

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent(x=50.0))
    courier.add_component(WorldPersistentActorComponent("courier"))
    courier.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    world = _seamless_world()
    world = replace(
        world,
        connections=(replace(world.connections[0], transition=TransitionMode.FADE),),
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: town if descriptor.instance_id == "town" else forest,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    player = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )

    assert system.travel("town-forest", anchor_id="party")
    assert player.get_component(TransformComponent).x == 50.0
    executor.complete(1)
    system.update()
    from expra_engine.runtime.events import FrameUpdate
    system.on_frame_update(FrameUpdate(0.0), None)

    assert system.transition.status is TransitionStatus.FADING_OUT
    assert player.get_component(TransformComponent).x == 50.0
    system.close()


def test_failed_seamless_destination_keeps_source_and_blocks_at_declared_exit() -> None:
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    actor = town.create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent())
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    attempts = 0

    def load_level(descriptor):
        nonlocal attempts
        if descriptor.instance_id == "forest":
            attempts += 1
            if attempts == 1:
                raise ValueError("broken forest fixture")
            return forest
        return town

    system = System(
        None,
        _seamless_world(),
        loader=load_level,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    courier.get_component(TransformComponent).x = 90.0
    system.update()
    executor.complete(1)
    system.update()
    assert system.state("forest").state is State.FAILED, system.snapshot()

    courier.get_component(TransformComponent).x = 99.0
    system.update()

    assert system.state("town").state is State.ACTIVE
    assert system.state("forest").state is State.FAILED
    assert system.runtime_scene.find_entity(courier.entity_id) is courier
    assert courier.get_component(TransformComponent).x == 100.0
    assert system.snapshot().last_transition_error is not None
    system.retry_level("forest")
    executor.complete(2)
    system.update()
    assert system.state("forest").state is State.ACTIVE
    assert system.current_level("party") == "forest"
    system.close()


def test_transition_pose_failure_does_not_move_persistent_actor_before_commit() -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from expra_engine.core.world import TransitionMode
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )
    from expra_engine.runtime.world_policy import PendingWorldTransition

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    actor = town.create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent(x=30.0))
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit"))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(TransformComponent(x=10.0))
    entry.add_component(LevelAnchorComponent("west", kind="entrance"))
    world = _seamless_world()
    world = replace(
        world,
        connections=(replace(world.connections[0], transition=TransitionMode.INSTANT),),
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: town if descriptor.instance_id == "town" else forest,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    runtime_actor = next(
        entity
        for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    system.request_load("forest")
    executor.complete(1)
    system.update()
    pending = PendingWorldTransition(
        "party", world.connections[0], (99.0, 0.0), "courier", runtime_actor.entity_id
    )

    with (
        patch.object(system, "_source_anchor_position", return_value=(110.0, 0.0)),
        patch.object(system.runtime_scene, "world_transform", side_effect=RuntimeError("bad pose")),
        pytest.raises(RuntimeError, match="bad pose"),
    ):
        system._commit_world_transition(pending, runtime_actor)

    assert runtime_actor.get_component(TransformComponent).x == 30.0
    assert system.current_level("party") == "town"
    system.close()


def test_seamless_connection_rejects_gaps_even_when_trigger_bounds_overlap() -> None:
    from expra_engine.core.world import WorldConnection
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    actor = town.create_entity("Courier")
    actor.add_component(TransformComponent(x=0.0))
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    exit_entity = town.create_entity("Exit")
    exit_entity.add_component(TransformComponent(x=100.0))
    exit_entity.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("Entry")
    entry.add_component(TransformComponent(x=1.0))
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    world = World(
        "Gap",
        world_id="gap",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
        ),
        connections=(
            WorldConnection(
                "east",
                "town",
                "east",
                "forest",
                "west",
                preload_distance=20.0,
                unload_distance=40.0,
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: town if descriptor.instance_id == "town" else forest,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    courier.get_component(TransformComponent).x = 90.0
    system.update()
    executor.complete(1)
    system.update()

    courier.get_component(TransformComponent).x = 99.0
    system.update()

    assert system.current_level("party") == "town"
    assert system.state("town").state is State.ACTIVE
    assert system.snapshot().last_transition_error is not None
    assert "not physically adjacent" in system.snapshot().last_transition_error
    system.close()


def test_residency_budget_exhaustion_blocks_crossing_without_crashing_source_world() -> None:
    from expra_engine.core.world import WorldConnection
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    town = Level("Town")
    actor = town.create_entity("Courier")
    actor.add_component(TransformComponent())
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    exit_entity = town.create_entity("Exit")
    exit_entity.add_component(TransformComponent(x=100.0))
    exit_entity.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    world = World(
        "Full World",
        world_id="full-world",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
        ),
        connections=(
            WorldConnection(
                "town-forest", "town", "east", "forest", "west",
                preload_distance=20.0, unload_distance=40.0,
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=1),
    )
    system = System(
        None,
        world,
        loader=lambda _descriptor: town,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()
    courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    courier.get_component(TransformComponent).x = 99.0

    system.update()

    assert system.state("town").state is State.ACTIVE
    assert system.state("forest").state is State.UNLOADED
    assert system.current_level("party") == "town"
    assert system.snapshot().last_transition_error is not None
    assert "budget" in system.snapshot().last_transition_error
    system.close()


def test_turning_away_cancels_preload_and_discards_late_level_result() -> None:
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )

    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town = Level("Town")
    actor = town.create_entity("Courier")
    actor.add_component(TransformComponent())
    actor.add_component(WorldPersistentActorComponent("courier"))
    actor.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    authored = {"town": town, "forest": forest}
    system = System(
        None,
        _seamless_world(),
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    courier = next(
        entity for entity in system.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    courier.get_component(TransformComponent).x = 90.0
    system.update()
    stale_generation = system.state("forest").generation
    assert system.state("forest").state is State.LOADING
    assert executor.jobs[1][0].set_running_or_notify_cancel()

    courier.get_component(TransformComponent).x = 0.0
    system.update()
    assert system.state("forest").state is State.CANCELLED

    executor.complete(1)
    system.update()

    assert system.state("forest").state is State.CANCELLED
    assert system.state("forest").generation > stale_generation
    assert system.snapshot().stale_results_discarded == 1
    assert system.state("town").state is State.ACTIVE
    system.close()


def test_world_instance_materialization_finishes_before_activation(monkeypatch) -> None:
    _Manager, State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    prepared: list[str] = []

    def materialize(level: Level, descriptor: LevelDescriptor, *, world_id: str) -> Level:
        prepared.append(descriptor.instance_id)
        return Level.from_dict(level.to_dict())

    world = World(
        "Preparation",
        world_id="prepare",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
        ),
        initial_level_id="town",
    )
    system = System(
        None,
        world,
        loader=lambda descriptor: Level(descriptor.instance_id),
        materializer=materialize,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete(0)
    system.update()
    system.request_load("forest")
    executor.complete(1)
    system.update()

    assert system.state("forest").state is State.LOADED
    assert prepared == ["town", "forest"]
    assert system.activate_level("forest")
    assert prepared == ["town", "forest"]
    system.close()


def test_scene_instance_pose_composes_with_world_origin_without_source_rewrite(tmp_path) -> None:
    from expra_engine.core.project import Project
    from expra_engine.core.scene import Scene, SceneInstanceComponent

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=1)
    project = Project.create("Placed Instances", tmp_path / "project")
    reusable = Scene("Reusable Tree", scene_id="tree-source")
    marker = reusable.create_entity("Tree Marker", entity_id="marker")
    marker.add_component(TransformComponent(x=2.0, y=3.0))
    project.save_document(reusable, "scenes/tree.scene.pb")
    town = Level("Town", scene_id="town-source")
    instance = town.create_entity("Tree Instance", entity_id="tree-instance")
    instance.add_component(TransformComponent(x=5.0, y=0.0))
    instance.add_component(SceneInstanceComponent("scenes/tree.scene.pb"))
    project.save_document(town, "levels/town.level.pb")
    source_bytes = project.document_file("levels/town.level.pb").read_bytes()
    world = World(
        "World",
        world_id="instance-world",
        levels=(LevelDescriptor("town", "levels/town.level.pb", origin=(100.0, 50.0)),),
        initial_level_id="town",
    )
    system = System(
        project,
        world,
        executor_factory=lambda workers: executor,
    )
    system.start(object())
    executor.complete()
    system.update()

    runtime_marker = next(
        entity for entity in system.runtime_scene.entities if entity.name == "Tree Marker"
    )
    assert system.runtime_scene.world_transform(runtime_marker.entity_id).position == (107.0, 53.0)
    assert project.document_file("levels/town.level.pb").read_bytes() == source_bytes
    system.close()


def test_primary_level_camera_mount_owns_world_hud_during_overlap() -> None:
    from dataclasses import replace

    import pygame

    from expra_engine.core.world import TransitionMode
    from expra_engine.runtime.camera_mount import CameraMountComponent
    from expra_engine.runtime.level_anchor import (
        LevelAnchorComponent,
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )
    from expra_engine.runtime.rendering import OrthographicCamera, RenderSpace
    from tests.support.pygame_renderer import make_renderer

    _Manager, _State, _CapacityError, System = _residency_types()
    executor = ManualExecutor(max_workers=2)
    town, forest = Level("Town"), Level("Forest")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent())
    courier.add_component(WorldPersistentActorComponent("courier"))
    courier.add_component(StreamingAnchorComponent("party"))
    courier.add_component(
        PrimitiveComponent("rectangle", width=4.0, height=4.0, fill=(0.0, 0.0, 1.0))
    )
    exit_entity = town.create_entity("East Gate")
    exit_entity.add_component(TransformComponent(x=100.0))
    exit_entity.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    town_hud = town.create_entity("Town HUD")
    town_hud.add_component(TransformComponent(x=900.0, y=300.0))
    town_hud.add_component(CameraMountComponent("top_left", x=16.0, y=-16.0))
    town_marker = town.create_entity("Town HUD Marker", parent_id=town_hud.entity_id)
    town_marker.add_component(
        PrimitiveComponent("rectangle", width=8.0, height=8.0, fill=(1.0, 0.0, 0.0))
    )
    entry = forest.create_entity("West Entry")
    entry.add_component(TransformComponent(x=1.0))
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    forest_hud = forest.create_entity("Forest HUD")
    forest_hud.add_component(CameraMountComponent("top_left", x=16.0, y=-16.0))
    forest_marker = forest.create_entity("Forest HUD Marker", parent_id=forest_hud.entity_id)
    forest_marker.add_component(
        PrimitiveComponent("rectangle", width=8.0, height=8.0, fill=(0.0, 1.0, 0.0))
    )
    world = _seamless_world()
    world = replace(
        world,
        connections=(replace(world.connections[0], transition=TransitionMode.INSTANT),),
    )
    authored = {"town": town, "forest": forest}
    system = System(
        None,
        world,
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: executor,
    )
    pygame.init()
    try:
        system.start(object())
        executor.complete(0)
        system.update()
        courier_runtime = next(
            entity for entity in system.runtime_scene.entities
            if entity.get_component(WorldPersistentActorComponent) is not None
        )
        courier_runtime.get_component(TransformComponent).x = 90.0
        system.update()
        executor.complete(1)
        system.update()
        courier_runtime.get_component(TransformComponent).x = 99.0
        system.update()
        assert system.current_level("party") == "forest"
        # Keep both Level document hierarchies resident/active to prove HUD
        # filtering does not accidentally draw the source HUD as World content.
        system.request_load("town")
        executor.complete(2)
        system.update()
        assert system.state("town").state is _State.ACTIVE, system.snapshot()
        assert system.state("forest").state.value == "active"
        town_marker_id = next(
            entity.entity_id
            for entity in system.runtime_scene.entities
            if entity.name == "Town HUD Marker"
        )
        forest_marker_id = next(
            entity.entity_id
            for entity in system.runtime_scene.entities
            if entity.name == "Forest HUD Marker"
        )
        before = system.runtime_scene.world_transform(town_marker_id)
        camera = OrthographicCamera(position=(100.0, 0.0), width=20.0, height=10.0)
        camera.position_smoothing_enabled = False
        def draw():
            frame = extract_render_frame(
                system.runtime_scene,
                primary_level_entity_ids=system.primary_level_entity_ids(),
            )
            renderer, surface = make_renderer(
                pygame, (200, 100), flags=pygame.SRCALPHA, clear_color=None, camera=camera
            )
            renderer.render(frame)
            assert not renderer.draw_failed
            mounted_ids = {
                item.key for item in frame.items if item.space is RenderSpace.VIEWPORT
            }
            assert town_marker_id not in mounted_ids
            assert forest_marker_id in mounted_ids
            return surface

        initial = draw()
        hud_bounds = color_bounds(initial, (0, 255, 0))
        courier_bounds = color_bounds(initial, (0, 0, 255))
        assert tuple(initial.get_at((16, 16))) == (0, 255, 0, 255)
        courier_runtime.get_component(TransformComponent).x = 105.0
        actor_moved = draw()
        assert color_bounds(actor_moved, (0, 255, 0)) == hud_bounds
        assert color_bounds(actor_moved, (0, 0, 255)) != courier_bounds
        camera.position = (104.0, 2.0)
        camera.zoom = 1.5
        camera.rotation = 0.25
        camera_moved = draw()
        assert color_bounds(camera_moved, (0, 255, 0)) == hud_bounds
        assert color_bounds(camera_moved, (0, 0, 255)) != color_bounds(
            actor_moved, (0, 0, 255)
        )
        assert system.runtime_scene.world_transform(town_marker_id) == before
    finally:
        system.close()
        pygame.quit()
