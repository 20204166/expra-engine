"""Versioned World session data and explicit UserDataStore persistence."""

import json
from concurrent.futures import Future
from pathlib import Path

import pytest

import expra_engine.runtime.world_materialize as world_materialize_module
import expra_engine.runtime.world_state as world_state_module
from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.filesystem import UserDataStore
from expra_engine.runtime.level_anchor import (
    StreamingAnchorComponent,
    WorldPersistentActorComponent,
)
from expra_engine.runtime.world_state import WorldSessionState, WorldSessionStateComponent
from expra_engine.runtime.world_streaming import WorldStreamingSystem

materialization_session_path = world_materialize_module._world_session_store_path
persistence_session_path = world_state_module._world_session_store_path

class ManualExecutor:
    def __init__(self, _workers: int) -> None:
        self.jobs: list[tuple[Future[object], object]] = []

    def submit(self, function):
        future: Future[object] = Future()
        self.jobs.append((future, function))
        return future

    def complete(self, index: int = 0) -> None:
        future, function = self.jobs[index]
        future.set_running_or_notify_cancel()
        future.set_result(function())

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        for future, _function in self.jobs:
            future.cancel()


def test_world_session_path_has_one_canonical_owner() -> None:
    assert materialization_session_path is persistence_session_path
    assert persistence_session_path("main", "quick").endswith("/quick.json")


def test_world_session_json_is_deterministic_and_preserves_all_gameplay_state() -> None:
    state = WorldSessionState("main-world", world_resource="worlds/main.world.pb")
    state.levels["town"] = {"door": {"open": True}}
    state.deleted_entities["town"] = {"enemy-1"}
    state.persistent_actors["courier"] = {
        "source_level_id": "town",
        "position": [101.0, 20.0],
        "state": {"health": 4},
    }
    state.current_levels["party"] = "forest"

    payload = state.to_json()
    restored = WorldSessionState.from_dict(json.loads(payload))

    assert payload == restored.to_json()
    assert restored.to_dict() == state.to_dict()


def test_world_session_rejects_unknown_versions_and_non_json_state() -> None:
    with pytest.raises(ValueError, match="schema version"):
        WorldSessionState.from_dict({"schema_version": 99, "world_id": "main-world"})
    with pytest.raises(ValueError, match="JSON"):
        WorldSessionState.from_dict(
            {
                "schema_version": 1,
                "world_id": "main-world",
                "levels": {"town": {"door": {"open": object()}}},
            }
        )


def test_level_session_restores_opted_in_values_and_authored_entity_deletions() -> None:
    authored = Level("Town")
    door = authored.create_entity("Door", entity_id="door")
    door.add_component(WorldSessionStateComponent({"open": False}))
    authored.create_entity("Enemy", entity_id="enemy")
    runtime = Level.from_dict(authored.to_dict())
    runtime.find_entity("door").get_component(WorldSessionStateComponent).values["open"] = True
    runtime.remove_entity("enemy")
    state = WorldSessionState("main-world")

    state.capture_level(
        "town",
        runtime,
        authored_entity_ids=("door", "enemy"),
    )
    restored = Level.from_dict(authored.to_dict())
    state.restore_level("town", restored)

    assert restored.find_entity("enemy") is None
    assert restored.find_entity("door").get_component(WorldSessionStateComponent).values == {
        "open": True
    }


def test_session_capture_does_not_persist_unidentified_runtime_spawned_entities() -> None:
    authored = Level("Town")
    door = authored.create_entity("Door", entity_id="door")
    door.add_component(WorldSessionStateComponent({"open": False}))
    runtime = Level.from_dict(authored.to_dict())
    runtime.create_entity("Spawned", entity_id="spawned").add_component(
        WorldSessionStateComponent({"state": "ephemeral"})
    )
    state = WorldSessionState("main-world")

    state.capture_level("town", runtime, authored_entity_ids=("door",))
    restored = Level.from_dict(authored.to_dict())
    state.restore_level("town", restored)

    assert "spawned" not in state.levels["town"]
    assert restored.find_entity("spawned") is None


def test_persistent_actor_snapshot_restores_opted_in_state_and_transform() -> None:
    actor = Level("Town").create_entity("Courier", entity_id="courier")
    actor.add_component(TransformComponent(x=12.0, y=4.0))
    actor.add_component(WorldPersistentActorComponent("player"))
    actor.add_component(WorldSessionStateComponent({"health": 6}))
    state = WorldSessionState("main-world")

    state.capture_persistent_actor("player", "town", (actor,))
    actor.get_component(TransformComponent).x = 0.0
    actor.get_component(WorldSessionStateComponent).values["health"] = 1
    state.restore_persistent_actor("player", (actor,))

    assert actor.get_component(TransformComponent).x == 12.0
    assert actor.get_component(WorldSessionStateComponent).values == {"health": 6}


def test_world_streaming_explicit_save_load_uses_user_data_and_restores_before_start(
    tmp_path: Path,
) -> None:
    authored = Level("Town")
    door = authored.create_entity("Door", entity_id="door")
    door.add_component(WorldSessionStateComponent({"open": False}))
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    store = UserDataStore(tmp_path / "userdata")
    first_executor = ManualExecutor(1)
    first = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: first_executor,
    )
    first.start(object())
    first_executor.complete()
    first.update()
    runtime_door = next(entity for entity in first.runtime_scene.entities if entity.name == "Door")
    runtime_door.get_component(WorldSessionStateComponent).values["open"] = True

    saved_path = first.save_session(store, slot="quick")
    first.close()

    second_executor = ManualExecutor(1)
    second = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: second_executor,
    )
    second.load_session(store, slot="quick")
    second.start(object())
    second_executor.complete()
    second.update()
    restored_door = next(entity for entity in second.runtime_scene.entities if entity.name == "Door")

    assert saved_path.endswith("quick.json")
    assert restored_door.get_component(WorldSessionStateComponent).values == {"open": True}
    assert authored.find_entity("door").get_component(WorldSessionStateComponent).values == {
        "open": False
    }
    before_failed_save = second.session_state
    restored_door.get_component(WorldSessionStateComponent).values["open"] = False

    class FailingStore(UserDataStore):
        def write_text(self, *_args, **_kwargs) -> None:
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        second.save_session(FailingStore(tmp_path / "failed"), slot="quick")
    assert second.session_state == before_failed_save
    assert restored_door.get_component(WorldSessionStateComponent).values == {"open": False}
    second.close()


def test_world_save_restores_persistent_actor_transform_before_level_activation(
    tmp_path: Path,
) -> None:
    from expra_engine.runtime.level_anchor import LevelAnchorComponent, LevelAnchorKind

    authored = Level("Town")
    courier = authored.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent(x=1.0, y=2.0))
    courier.add_component(WorldPersistentActorComponent("player"))
    courier.add_component(StreamingAnchorComponent("party"))
    courier.add_component(WorldSessionStateComponent({"health": 8}))
    entrance = authored.create_entity("Start", entity_id="start")
    entrance.add_component(TransformComponent(x=12.0, y=18.0))
    entrance.add_component(LevelAnchorComponent("start", kind=LevelAnchorKind.ENTRANCE))
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        primary_anchor_id="party",
        initial_level_id="town",
        initial_entrance_id="start",
    )
    store = UserDataStore(tmp_path / "userdata")
    first_executor = ManualExecutor(1)
    first = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: first_executor,
    )
    first.start(object())
    first_executor.complete()
    first.update()
    player = next(
        entity
        for entity in first.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    player.get_component(TransformComponent).x = 45.0
    player.get_component(WorldSessionStateComponent).values["health"] = 3
    first.save_session(store, slot="quick")
    first.close()

    second_executor = ManualExecutor(1)
    second = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: second_executor,
    )
    second.load_session(store, slot="quick")
    second.start(object())
    second_executor.complete()
    second.update()
    restored = next(
        entity
        for entity in second.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )

    assert restored.get_component(TransformComponent).x == 45.0
    assert restored.get_component(WorldSessionStateComponent).values == {"health": 3}
    assert authored.find_entity("courier").get_component(TransformComponent).x == 1.0
    second.close()


def test_world_startup_uses_saved_primary_level_instead_of_authored_initial_level(
    tmp_path: Path,
) -> None:
    from expra_engine.core.world import TransitionMode, WorldConnection
    from expra_engine.runtime.level_anchor import LevelAnchorComponent

    town = Level("Town")
    courier = town.create_entity("Courier", entity_id="courier")
    courier.add_component(TransformComponent())
    courier.add_component(WorldPersistentActorComponent("player"))
    courier.add_component(StreamingAnchorComponent("party"))
    gate = town.create_entity("East Gate")
    gate.add_component(TransformComponent(x=100.0))
    gate.add_component(LevelAnchorComponent("east", kind="exit", size=(4.0, 4.0)))
    forest = Level("Forest")
    entry = forest.create_entity("West Entry")
    entry.add_component(LevelAnchorComponent("west", kind="entrance", size=(4.0, 4.0)))
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
        ),
        connections=(
            WorldConnection(
                "town-forest",
                "town",
                "east",
                "forest",
                "west",
                bidirectional=True,
                transition=TransitionMode.INSTANT,
            ),
        ),
        primary_anchor_id="party",
        initial_level_id="town",
    )
    authored = {"town": town, "forest": forest}
    store = UserDataStore(tmp_path / "userdata")
    first_executor = ManualExecutor(2)
    first = WorldStreamingSystem(
        None,
        world,
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: first_executor,
    )
    first.start(object())
    first_executor.complete(0)
    first.update()
    player = next(
        entity for entity in first.runtime_scene.entities
        if entity.get_component(WorldPersistentActorComponent) is not None
    )
    player.get_component(TransformComponent).x = 90.0
    first.update()
    first_executor.complete(1)
    first.update()
    player.get_component(TransformComponent).x = 99.0
    first.update()
    assert first.current_level("party") == "forest"
    first.save_session(store, slot="quick")
    first.close()

    second_executor = ManualExecutor(2)
    second = WorldStreamingSystem(
        None,
        world,
        loader=lambda descriptor: authored[descriptor.instance_id],
        executor_factory=lambda workers: second_executor,
    )
    second.load_session(store, slot="quick")
    second.start(object())
    second_executor.complete(0)
    second.update()
    second_executor.complete(1)
    second.update()

    assert second.current_level("party") == "forest"
    assert second.state("forest").state.value == "active"
    assert second.world.initial_level_id == "town"
    second.close()


def test_save_restart_restores_component_state_and_deleted_authored_entity(tmp_path: Path) -> None:
    authored = Level("Town")
    door = authored.create_entity("Door", entity_id="door")
    door.add_component(WorldSessionStateComponent({"open": False}))
    authored.create_entity("Enemy", entity_id="enemy")
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    store = UserDataStore(tmp_path / "userdata")

    first_executor = ManualExecutor(1)
    first = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: first_executor,
    )
    first.start(object())
    first_executor.complete()
    first.update()
    runtime_door = next(entity for entity in first.runtime_scene.entities if entity.name == "Door")
    runtime_enemy = next(entity for entity in first.runtime_scene.entities if entity.name == "Enemy")
    runtime_door.get_component(WorldSessionStateComponent).values["open"] = True
    first.runtime_scene.remove_entity(runtime_enemy.entity_id, recursive=True)
    first.save_session(store, slot="resume")
    first.close()

    second_executor = ManualExecutor(1)
    second = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: second_executor,
    )
    second.load_session(store, slot="resume")
    second.start(object())
    second_executor.complete()
    second.update()

    restored_door = next(entity for entity in second.runtime_scene.entities if entity.name == "Door")
    assert restored_door.get_component(WorldSessionStateComponent).values == {"open": True}
    assert not any(entity.name == "Enemy" for entity in second.runtime_scene.entities)
    assert authored.find_entity("enemy") is not None
    assert authored.find_entity("door").get_component(WorldSessionStateComponent).values == {
        "open": False
    }
    second.close()
