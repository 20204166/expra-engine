"""Acceptance coverage for the project-owned Blacksite Relay dogfood game."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.script_component import ScriptComponent
from tests.support.project_engine import load_project_engine

PROJECT_DIR = Path(__file__).parents[1] / "examples" / "blacksite_relay"


def _project_engine() -> tuple[Project, Engine]:
    return load_project_engine(PROJECT_DIR)


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
