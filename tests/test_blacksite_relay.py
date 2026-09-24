"""Acceptance coverage for the project-owned Blacksite Relay dogfood game."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry
from tests.support.project_engine import load_project_engine

PROJECT_DIR = Path(__file__).parents[1] / "examples" / "blacksite_relay"
LEVEL_2_SCENE = "scenes/level_02_deepcore.json"


def _project_engine() -> tuple[Project, Engine]:
    return load_project_engine(PROJECT_DIR)


def _project_engine_for_scene(relative_path: str) -> tuple[Project, Engine]:
    project = Project.load(PROJECT_DIR)
    engine = Engine()
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(project.load_scene(relative_path))
    return project, engine


def _drive_player(game: Any, actions: tuple[str, ...], ticks: int, dt: float = 1 / 60) -> None:
    with patch.object(game.input, "is_held", side_effect=lambda action: action in actions):
        for _ in range(ticks):
            game.on_fixed_update(dt)


def test_blacksite_relay_project_loads_scripts_and_asset_backed_scene() -> None:
    project = Project.load(PROJECT_DIR)
    scene = project.load_scene()

    assert project.name == "Blacksite Relay"
    assert project.start_scene == "scenes/main.json"
    assert len(scene.entities) >= 60
    assert {"player", "enemy", "shard", "vip", "extraction"} <= {
        tag for entity in scene.entities for tag in entity.tags
    }
    script_components = [
        component
        for entity in scene.entities
        for component in entity.components
        if isinstance(component, ScriptComponent)
    ]
    assert len(script_components) == 1
    assert str(script_components[0].script_id) == "project://scripts/blacksite_relay_behaviour.py"
    assert all(
        (PROJECT_DIR / "assets" / "kenney" / filename).is_file()
        for filename in (
            "floor_panel.png",
            "player_survivor_gun.png",
            "survivor_blue.png",
            "zombie.png",
        )
    )


def test_blacksite_relay_starts_renders_pauses_restarts_and_preserves_saved_scene() -> None:
    project, engine = _project_engine()
    saved = json.loads(project.scene_file().read_text(encoding="utf-8"))

    assert engine.play()
    game = cast(Any, engine.behaviour_system.instances[0])
    assert type(game).__name__ == "BlacksiteRelayBehaviour"
    assert game.state == "playing"
    assert game.health == 5
    scene = engine.active_scene
    assert scene is not None
    assert len(extract_render_frame(scene).items) >= 20

    assert game._toggle_pause() is True
    assert engine.run_state is EngineRunState.PAUSED
    assert game._toggle_pause() is True
    assert engine.run_state is EngineRunState.PLAY
    assert game._restart() is True
    assert engine.run_state is EngineRunState.PLAY
    restarted = cast(Any, engine.behaviour_system.instances[0])
    assert restarted.state == "playing"
    assert restarted.health == 5

    engine.stop()
    assert json.loads(project.scene_file().read_text(encoding="utf-8")) == saved


def test_project_registers_both_levels() -> None:
    project = Project.load(PROJECT_DIR)

    assert project.scene_paths() == ("scenes/main.json", LEVEL_2_SCENE)
    assert project.start_scene == "scenes/main.json"


def test_level_2_loads_with_its_own_entities_and_objectives() -> None:
    project = Project.load(PROJECT_DIR)
    scene = project.load_scene(LEVEL_2_SCENE)

    assert scene.scene_id == "blacksite-relay-level-02-deepcore"
    assert len(scene.entities) > 90
    tags = {tag for entity in scene.entities for tag in entity.tags}
    assert {"player", "enemy", "shard", "vip", "extraction", "game_controller"} <= tags
    assert sum(1 for e in scene.entities if "shard" in e.tags) == 4
    assert sum(1 for e in scene.entities if "vip" in e.tags) == 1
    script_components = [
        component
        for entity in scene.entities
        for component in entity.components
        if isinstance(component, ScriptComponent)
    ]
    assert len(script_components) == 1
    assert str(script_components[0].script_id) == "project://scripts/blacksite_relay_behaviour.py"
    exposed = script_components[0].exposed_values
    assert exposed["arena_half_width"] == 54.5
    assert exposed["arena_half_height"] == 23.0


def test_same_behaviour_class_enforces_per_scene_arena_bounds() -> None:
    """The shared BlacksiteRelayBehaviour must clamp to each scene's own
    arena size: level 1 stays at its original bounds, level 2 doubles."""
    _project1, engine1 = _project_engine()
    assert engine1.play()
    game1 = cast(Any, engine1.behaviour_system.instances[0])
    assert game1.arena_half_width == 38.5
    assert game1.arena_half_height == 16.2
    t1 = game1._transform("player")
    t1.x, t1.y = 37.0, 15.0
    _drive_player(game1, ("move_right", "move_up"), ticks=200)
    assert t1.x == 38.5
    assert t1.y == 16.2
    engine1.stop()

    _project2, engine2 = _project_engine_for_scene(LEVEL_2_SCENE)
    assert engine2.play()
    game2 = cast(Any, engine2.behaviour_system.instances[0])
    assert game2.arena_half_width == 54.5
    assert game2.arena_half_height == 23.0
    t2 = game2._transform("player")
    t2.x, t2.y = 53.0, 22.0
    _drive_player(game2, ("move_right", "move_up"), ticks=200)
    assert t2.x == 54.5
    assert t2.y == 23.0
    engine2.stop()


def test_level_2_plays_end_to_end_with_extended_mission_clock() -> None:
    project, engine = _project_engine_for_scene(LEVEL_2_SCENE)
    assert engine.play()
    game = cast(Any, engine.behaviour_system.instances[0])

    assert game.mission_seconds == 165.0
    assert game.state == "playing"
    scene = engine.active_scene
    assert scene is not None
    assert len(extract_render_frame(scene).items) >= 80

    engine.stop()
    assert project.scene_file(LEVEL_2_SCENE).exists()


def test_create_runtime_selects_the_requested_scene() -> None:
    """__main__.create_runtime's optional scene_path must not change the
    default (no-arg) behaviour, and must correctly load level 2 on request.
    The renderer/resource-provider construction is mocked out (patched on
    the consuming __main__ module, matching how it was imported via
    `from ... import`) since this test only cares which scene gets loaded,
    not the pixel pipeline."""
    import examples.blacksite_relay.__main__ as entrypoint

    assert entrypoint.LEVEL_SCENES["main"] == "scenes/main.json"
    assert entrypoint.LEVEL_SCENES["level2"] == LEVEL_2_SCENE
    assert entrypoint.LEVEL_SCENES["deepcore"] == LEVEL_2_SCENE

    with (
        patch.object(entrypoint, "PygameRenderer"),
        patch.object(entrypoint, "PygameResourceProvider"),
    ):
        runtime_default = entrypoint.create_runtime(MagicMock())
        assert runtime_default.engine.active_scene is not None
        assert runtime_default.engine.active_scene.scene_id == "blacksite-relay-main"
        runtime_default.engine.stop()

        runtime_level2 = entrypoint.create_runtime(MagicMock(), LEVEL_2_SCENE)
        assert runtime_level2.engine.active_scene is not None
        assert runtime_level2.engine.active_scene.scene_id == "blacksite-relay-level-02-deepcore"
        runtime_level2.engine.stop()


def test_main_dispatches_argv_to_level_scenes() -> None:
    """main()'s sys.argv[1] shorthand must resolve to the right scene and
    reject an unknown level name rather than silently falling back."""
    import examples.blacksite_relay.__main__ as entrypoint

    seen: list[str | None] = []

    def fake_create_runtime(_pygame_module: Any, scene_path: str | None = None) -> Any:
        seen.append(scene_path)
        return MagicMock()

    with (
        patch.object(entrypoint, "create_runtime", side_effect=fake_create_runtime),
        patch.object(entrypoint.sys, "argv", ["blacksite_relay"]),
    ):
        entrypoint.main()
    assert seen == ["scenes/main.json"]

    seen.clear()
    with (
        patch.object(entrypoint, "create_runtime", side_effect=fake_create_runtime),
        patch.object(entrypoint.sys, "argv", ["blacksite_relay", "level2"]),
    ):
        entrypoint.main()
    assert seen == [LEVEL_2_SCENE]

    with (
        patch.object(entrypoint.sys, "argv", ["blacksite_relay", "nope"]),
        pytest.raises(SystemExit),
    ):
        entrypoint.main()
