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
