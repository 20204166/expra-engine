"""Standalone runner dispatches typed World entrypoints through Engine."""

from pathlib import Path
from unittest.mock import patch

import pytest

from expra_engine.core.project import Project
from expra_engine.core.scene import Level
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.runtime.project_runner import run_project


def test_run_project_plays_and_closes_world_runtime_for_world_entrypoint(tmp_path: Path) -> None:
    project = Project.create("World Game", tmp_path / "project")
    project.save_document(Level("Town"), "levels/town.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    project.save_document(world, "worlds/main.world.pb")
    project.set_entrypoint("worlds/main.world.pb")
    project.save()
    captured = {}

    class FakeRenderer:
        def __init__(self, *_args, **kwargs) -> None:
            captured["observer"] = kwargs["observer"]

    class FakeResourceProvider:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeRuntime:
        def __init__(self, engine, *_args, **_kwargs) -> None:
            captured["engine"] = engine

        def run(self) -> None:
            engine = captured["engine"]
            assert engine.world is not None
            assert engine.world.world_id == "main"
            assert engine.world_streaming_system is not None
            captured["system"] = engine.world_streaming_system
            engine.stop()

    with (
        patch("expra_engine.runtime.project_runner.PygameRenderer", FakeRenderer),
        patch("expra_engine.runtime.project_runner.PygameResourceProvider", FakeResourceProvider),
        patch("expra_engine.runtime.project_runner.PygameRuntime", FakeRuntime),
    ):
        run_project(project.path)

    assert captured["engine"].run_state.value == "edit"
    assert captured["system"]._closed is True


def test_run_project_surfaces_initial_level_load_failure(tmp_path: Path) -> None:
    project = Project.create("Broken World", tmp_path / "project")
    project.save_document(Level("Town"), "levels/town.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
        initial_entrance_id="missing-entry",
    )
    project.save_document(world, "worlds/main.world.pb")
    project.set_entrypoint("worlds/main.world.pb")
    project.save()

    class FakeRenderer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeResourceProvider:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeRuntime:
        def __init__(self, engine, *_args, frame_factory, **_kwargs) -> None:
            self.engine = engine
            self.frame_factory = frame_factory

        def run(self) -> None:
            system = self.engine.world_streaming_system
            assert system is not None
            if system.startup_error is None:
                future = next(iter(system._futures.values()))[1]
                with pytest.raises(ValueError):
                    future.result(timeout=5)
                self.engine.tick(0.0)
            self.frame_factory(self.engine, 0.0)

    with (
        patch("expra_engine.runtime.project_runner.PygameRenderer", FakeRenderer),
        patch("expra_engine.runtime.project_runner.PygameResourceProvider", FakeResourceProvider),
        patch("expra_engine.runtime.project_runner.PygameRuntime", FakeRuntime),
        pytest.raises(RuntimeError, match=r"World startup Level 'town' failed.*missing-entry"),
    ):
        run_project(project.path)


def test_run_project_marks_level_hud_as_viewport_space(tmp_path: Path) -> None:
    import time

    from expra_engine.core.component import TransformComponent
    from expra_engine.runtime.camera_mount import CameraMountComponent
    from expra_engine.runtime.rendering import RenderSpace
    from expra_engine.runtime.visual_components import PrimitiveComponent

    project = Project.create("HUD Game", tmp_path / "project")
    level = Level("Town")
    hud = level.create_entity("Town HUD")
    hud.add_component(CameraMountComponent("top_left", x=12.0, y=-12.0))
    marker = level.create_entity("Town Marker", parent_id=hud.entity_id)
    marker.add_component(TransformComponent(x=24.0, y=4.0))
    marker.add_component(PrimitiveComponent("rectangle", fill=(1.0, 0.0, 0.0)))
    project.save_document(level, "levels/town.level.pb")
    forest = Level("Forest")
    forest_hud = forest.create_entity("Forest HUD")
    forest_hud.add_component(CameraMountComponent("top_left", x=12.0, y=-12.0))
    forest.create_entity("Forest Marker", parent_id=forest_hud.entity_id).add_component(
        PrimitiveComponent("rectangle", fill=(0.0, 1.0, 0.0))
    )
    project.save_document(forest, "levels/forest.level.pb")
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
        ),
        initial_level_id="town",
    )
    project.save_document(world, "worlds/main.world.pb")
    project.set_entrypoint("worlds/main.world.pb")
    project.save()
    captured = {}

    class FakeRenderer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def render(self, frame) -> None:
            captured["frame"] = frame

        def stop(self) -> None:
            pass

    class FakeResources:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeRuntime:
        def __init__(self, engine, renderer, *, frame_factory, **_kwargs) -> None:
            self.engine = engine
            self.renderer = renderer
            self.frame_factory = frame_factory

        def run(self) -> None:
            system = self.engine.world_streaming_system
            deadline = time.monotonic() + 5.0
            while "town" not in system.active_levels():
                assert time.monotonic() < deadline, system.snapshot()
                self.engine.tick(0.016)
                time.sleep(0.005)
            system.request_load("forest")
            while system.state("forest").state.value != "loaded":
                assert time.monotonic() < deadline, system.snapshot()
                self.engine.tick(0.016)
                time.sleep(0.005)
            assert system.activate_level("forest")
            town_marker_id = next(
                entity.entity_id for entity in self.engine.active_scene.entities
                if entity.name == "Town Marker"
            )
            self.renderer.render(self.frame_factory(self.engine, 0.016))
            captured["town_marker_id"] = town_marker_id
            self.engine.stop()

    with (
        patch("expra_engine.runtime.project_runner.PygameRenderer", FakeRenderer),
        patch("expra_engine.runtime.project_runner.PygameResourceProvider", FakeResources),
        patch("expra_engine.runtime.project_runner.PygameRuntime", FakeRuntime),
    ):
        run_project(project.path)

    viewport_items = {
        item.key for item in captured["frame"].items if item.space is RenderSpace.VIEWPORT
    }
    assert viewport_items == {captured["town_marker_id"]}, [
        (item.key, item.space.value)
        for item in captured["frame"].items
    ]
