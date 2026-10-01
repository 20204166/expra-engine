"""Engine lifecycle composition for World streaming."""

from __future__ import annotations

from expra_engine.core.engine import Engine
from expra_engine.core.scene import Level, Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry
from expra_engine.runtime.system import RuntimeSystem
from tests.support.scheduling import ManualExecutor


def test_engine_play_runs_world_runtime_and_stop_restores_edit_scene() -> None:
    from expra_engine.runtime.world_streaming import WorldStreamingSystem

    world = World(
        "World",
        world_id="world",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    executor = ManualExecutor(1)
    system = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: _level_with_player(),
        executor_factory=lambda workers: executor,
    )
    engine = Engine()
    edit_scene = Scene("Edit")
    engine.set_scene(edit_scene)

    engine.set_world(world, streaming_system=system)
    assert engine.play()
    assert engine.active_scene is system.runtime_scene
    executor.complete()
    engine.tick(0.0)
    assert engine.active_scene is system.runtime_scene
    assert any(entity.name == "Courier" for entity in engine.active_scene.entities)

    assert engine.stop()
    assert engine.edit_scene is edit_scene
    system.close()


def test_world_level_activation_starts_and_deactivation_stops_behaviours(tmp_path) -> None:
    from expra_engine.core.project import Project
    from expra_engine.runtime.world_streaming import WorldStreamingSystem

    project = Project.create("World Behaviours", tmp_path / "project")
    scripts = project.scripts_dir
    (scripts / "world_actor.py").write_text(
        "from expra_engine.runtime.behaviour import Behaviour\n"
        "class WorldActor(Behaviour):\n"
        "    def on_start(self): self.started = True\n"
        "    def on_stop(self): self.stopped = True\n",
        encoding="utf-8",
    )
    world = World(
        "World",
        world_id="world",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    authored = _level_with_player()
    authored.entities[0].add_component(
        ScriptComponent("project://scripts/world_actor.py", "WorldActor")
    )
    executor = ManualExecutor(1)
    system = WorldStreamingSystem(
        project,
        world,
        loader=lambda _descriptor: authored,
        executor_factory=lambda workers: executor,
    )
    engine = Engine()
    engine.set_world(world, project=project, streaming_system=system)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.play()
    executor.complete()
    engine.tick(0.0)

    instances = engine.behaviour_system.instances
    assert len(instances) == 1
    assert instances[0].started is True
    assert system.deactivate_level("town")
    assert engine.behaviour_system.instances == ()
    assert instances[0].stopped is True

    assert system.activate_level("town")
    assert len(engine.behaviour_system.instances) == 1
    engine.stop()
    system.close()


def test_world_level_services_start_before_a_persistent_player_behaviour(tmp_path) -> None:
    from expra_engine.core.component import TransformComponent
    from expra_engine.core.project import Project
    from expra_engine.runtime.level_anchor import (
        StreamingAnchorComponent,
        WorldPersistentActorComponent,
    )
    from expra_engine.runtime.world_streaming import LevelResidencyState, WorldStreamingSystem

    project = Project.create("World Bootstrap Ordering", tmp_path / "project")
    (project.scripts_dir / "actors.py").write_text(
        "from expra_engine.runtime.behaviour import Behaviour\n"
        "class CombatRulesBehaviour(Behaviour):\n"
        "    pass\n"
        "class PlayerBehaviour(Behaviour):\n"
        "    def on_start(self):\n"
        "        service = self.scene.get_entities_by_tag('combat_rules')[0]\n"
        "        if not any(type(item).__name__ == 'CombatRulesBehaviour' "
        "for item in service.behaviours):\n"
        "            raise LookupError('combat service must start before player')\n",
        encoding="utf-8",
    )
    level = Level("Town")
    player = level.create_entity("Courier", entity_id="courier")
    player.add_component(TransformComponent())
    player.add_component(WorldPersistentActorComponent("courier"))
    player.add_component(StreamingAnchorComponent("player"))
    player.add_component(ScriptComponent("project://scripts/actors.py", "PlayerBehaviour"))
    rules = level.create_entity("Combat Rules", entity_id="combat-rules")
    rules.add_tag("combat_rules")
    rules.add_component(ScriptComponent("project://scripts/actors.py", "CombatRulesBehaviour"))
    executor = ManualExecutor(1)
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        primary_anchor_id="player",
        initial_level_id="town",
    )
    system = WorldStreamingSystem(
        project,
        world,
        loader=lambda _descriptor: level,
        executor_factory=lambda workers: executor,
    )
    engine = Engine()
    engine.set_world(world, project=project, streaming_system=system)
    engine.set_script_registry(ScriptRegistry(project.path))

    assert engine.play()
    executor.complete()
    engine.tick(0.0)

    assert system.state("town").state is LevelResidencyState.ACTIVE
    assert {type(item).__name__ for item in engine.behaviour_system.instances} == {
        "PlayerBehaviour",
        "CombatRulesBehaviour",
    }
    engine.stop()
    system.close()


def _level_with_player() -> Level:
    level = Level("Town", scene_id="town-source")
    level.create_entity("Courier", entity_id="courier")
    return level


def test_runtime_system_contract_names_world_level_lifecycle_hooks() -> None:
    system = RuntimeSystem()

    assert callable(getattr(system, "on_world_level_activated", None))
    assert callable(getattr(system, "on_world_level_deactivated", None))


def test_failed_level_activation_rolls_back_prior_runtime_system_hooks() -> None:
    import pytest

    class Recorder(RuntimeSystem):
        def __init__(self) -> None:
            self.events: list[str] = []

        def on_world_level_activated(self, _world, _level_id, _level) -> None:
            self.events.append("activated")

        def on_world_level_deactivated(self, _world, _level_id, _level) -> None:
            self.events.append("deactivated")

    class Failure(RuntimeSystem):
        def on_world_level_activated(self, _world, _level_id, _level) -> None:
            raise RuntimeError("activation rejected")

    engine = Engine()
    engine.set_scene(Scene("World runtime"))
    recorder = Recorder()
    engine.add_system(recorder)
    engine.add_system(Failure())

    with pytest.raises(RuntimeError, match="activation rejected"):
        engine.notify_world_level_activated("town", Level("Town"))

    assert recorder.events == ["activated", "deactivated"]


def test_world_level_deactivation_discards_pending_entity_targeted_events() -> None:
    from dataclasses import dataclass

    @dataclass
    class Ping:
        pass

    engine = Engine()
    scene = Scene("World")
    entity = scene.create_entity("temporary", entity_id="temporary")
    engine.set_scene(scene)
    engine.play()
    runtime_entity = engine.active_scene.find_entity(entity.entity_id)
    assert runtime_entity is not None
    received: list[Ping] = []
    runtime_entity.on_ping = lambda event, _signal: received.append(event)
    engine._eq.signal(Ping(), targets=(runtime_entity,))

    engine.notify_world_level_deactivated("town", (entity.entity_id,))
    engine._eq.drain()

    assert received == []
    engine.stop()


def test_world_activation_hook_failure_never_exposes_a_partial_active_level() -> None:
    from expra_engine.runtime.world_streaming import LevelResidencyState, WorldStreamingSystem

    class FailingSystem(RuntimeSystem):
        def on_world_level_activated(self, _world, _level_id, _level) -> None:
            raise RuntimeError("test activation failure")

    world = World(
        "World",
        world_id="world",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    executor = ManualExecutor(1)
    system = WorldStreamingSystem(
        None,
        world,
        loader=lambda _descriptor: _level_with_player(),
        executor_factory=lambda workers: executor,
    )
    engine = Engine()
    engine.set_world(world, streaming_system=system)
    engine.add_system(FailingSystem())
    engine.play()
    executor.complete()

    engine.tick(0.0)

    assert system.state("town").state is LevelResidencyState.FAILED
    assert not any(entity.name == "Courier" for entity in engine.active_scene.entities)
    assert engine.world_lifecycle_errors == (
        "activation town: RuntimeError: test activation failure",
    )
    engine.stop()
    system.close()
