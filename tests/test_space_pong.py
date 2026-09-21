"""Task 7 acceptance tests for the project-owned Space Pong dogfood game."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.project import Project
from expra_engine.export.exporter import GameExporter
from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch, RuntimeProfile
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent


PROJECT_DIR = Path(__file__).parents[1] / "examples" / "space_pong"


def _project_engine() -> tuple[Project, Engine]:
    project = Project.load(PROJECT_DIR)
    engine = Engine()
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(project.load_scene())
    return project, engine


def test_space_pong_project_uses_generic_scene_components_and_project_scripts() -> None:
    project = Project.load(PROJECT_DIR)
    scene = project.load_scene()
    registered = {name for name, _ in __import__(
        "expra_engine.core.component", fromlist=["registered_component_types"]
    ).registered_component_types()}

    assert project.name == "Space Pong"
    assert project.start_scene == "scenes/main.json"
    assert len(scene.entities) >= 8
    assert {component.component_type for entity in scene.entities for component in entity.components} <= registered | {"script"}
    script_components = [
        component
        for entity in scene.entities
        for component in entity.components
        if isinstance(component, ScriptComponent)
    ]
    assert script_components
    assert {str(component.script_id) for component in script_components} == {
        "project://scripts/space_pong_behaviour.py"
    }
    assert any(isinstance(component, PrimitiveComponent) for entity in scene.entities for component in entity.components)
    assert any(isinstance(component, TextComponent) for entity in scene.entities for component in entity.components)
    assert any(isinstance(component, ColliderComponent) for entity in scene.entities for component in entity.components)


def test_space_pong_opens_resolves_scripts_runs_and_stops_without_mutating_saved_scene() -> None:
    project, engine = _project_engine()
    saved = json.loads(project.scene_file().read_text(encoding="utf-8"))

    assert engine.play()
    behaviours = engine.behaviour_system.instances
    assert len(behaviours) == 1
    game = behaviours[0]
    assert type(game).__name__ == "SpacePongBehaviour"
    assert engine.active_scene is not engine.edit_scene
    engine.stop()

    assert engine.run_state is EngineRunState.EDIT
    assert json.loads(project.scene_file().read_text(encoding="utf-8")) == saved


def test_space_pong_runtime_covers_score_win_pause_restart_and_hit_feedback() -> None:
    _, engine = _project_engine()
    engine.play()
    game = engine.behaviour_system.instances[0]

    game.score_point("left")
    game.score_point("left")
    assert game.score == (2, 0)
    assert game.status == "playing"
    assert game.hit_feedback > 0.0
    game.score_point("left")
    assert game.status == "won"
    assert game.winner == "left"

    assert game.toggle_pause() is True
    assert engine.run_state is EngineRunState.PAUSED
    assert game.toggle_pause() is True
    assert engine.run_state is EngineRunState.PLAY

    assert game.restart() is True
    assert engine.run_state is EngineRunState.PLAY
    restarted = engine.behaviour_system.instances[0]
    assert restarted.score == (0, 0)
    assert restarted.status == "playing"
    engine.stop()


def test_space_pong_ball_bounce_is_deterministic_at_the_arena_wall() -> None:
    _, engine = _project_engine()
    engine.play()
    game = engine.behaviour_system.instances[0]
    game.ball_velocity = (4.0, 12.0)
    game._transform("ball").y = 27.5

    game.on_fixed_update(0.1)

    assert game.ball_velocity == (4.0, -12.0)
    engine.stop()


def test_space_pong_hud_layout_is_stable_across_resize_and_render_extraction_is_generic() -> None:
    _, engine = _project_engine()
    engine.play()
    game = engine.behaviour_system.instances[0]
    first = game.resize((800, 600))["score_left"]
    second = game.resize((1600, 900))["score_left"]
    assert first.x / 800 == second.x / 1600
    assert first.y / 600 == second.y / 900

    frame = extract_render_frame(engine.active_scene)
    assert frame.items
    assert all(item.key for item in frame.items)
    engine.stop()


def test_space_pong_save_reopen_and_export_workflow(tmp_path: Path) -> None:
    project, _ = _project_engine()
    scene = project.load_scene()
    project.save_scene(scene)
    reopened = Project.load(PROJECT_DIR)
    assert reopened.load_scene().to_dict() == scene.to_dict()

    output = tmp_path / "builds"
    plan = ExportPlan(
        project_dir=PROJECT_DIR,
        entry_point="__main__.py",
        output_dir=output,
        target=ExportTarget.LINUX,
        game_name="Space Pong",
        game_version=reopened.game_version,
        python_version="3.12.0",
        arch=PythonArch.AMD64,
        compile_bytecode=False,
        debug_launcher=True,
        runtime_profile=RuntimeProfile.NONE,
    )
    result = GameExporter(packager=_Packager()).export(plan, cancel=threading.Event())
    assert (result / "Space_Pong" / "project.json").is_file()
    assert (result / "Space_Pong" / "scripts" / "space_pong_behaviour.py").is_file()
    assert (result / "Space_Pong" / "scenes" / "main.json").is_file()
    assert (result / "Space_Pong" / "__main__.py").is_file()


def test_space_pong_standalone_entry_point_runs_the_standard_runtime_path() -> None:
    from examples.space_pong.__main__ import create_runtime

    pygame = _StandalonePygame()
    runtime = create_runtime(pygame)
    runtime.run()
    assert pygame.display.sizes == [(960, 640)]
    assert pygame.flips == 1
    runtime.engine.stop()


class _Packager:
    def install_runtime(self, python_version, arch, dest, *, cache_dir, cancel, progress, downloader=None):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "bin").mkdir()
        (dest / "bin" / "python3").write_text("placeholder")

    def install_packages(self, packages, python_version, arch, site_packages, *, cache_dir, cancel, progress):
        site_packages.mkdir(parents=True, exist_ok=True)

    def make_launcher(self, build_dir, game_name, entry_point, source_subdir, *, is_pyc, debug):
        suffix = "_debug" if debug else ""
        (build_dir / f"Space_Pong{suffix}.sh").write_text("#!/bin/sh\n")


class _StandalonePygame:
    QUIT = 1
    KEYDOWN = 2
    KEYUP = 3
    VIDEORESIZE = 4
    MOUSEMOTION = 5
    MOUSEBUTTONDOWN = 6
    MOUSEBUTTONUP = 7

    class _Display:
        def __init__(self, owner: _StandalonePygame) -> None:
            self.owner = owner
            self.sizes: list[tuple[int, int]] = []

        def set_mode(self, size: tuple[int, int]) -> object:
            self.sizes.append(size)
            return self.owner._Surface()

        def flip(self) -> None:
            self.owner.flips += 1

    class _Clock:
        def tick(self, frame_rate: int) -> int:
            return 16

    class _Surface:
        def blit(self, rendered: object, position: object) -> None:
            pass

    class _Font:
        def size(self, text: str) -> tuple[int, int]:
            return (max(1, len(text)) * 8, 16)

        def render(self, text: str, antialias: bool, color: tuple[int, ...]) -> object:
            return object()

    class _Draw:
        def rect(self, surface: object, color: tuple[int, ...], rectangle: object, *args: object) -> None:
            pass

        def circle(self, surface: object, color: tuple[int, ...], center: object, radius: int) -> None:
            pass

    def __init__(self) -> None:
        self.flips = 0
        self.display = self._Display(self)
        self.event = SimpleNamespace(get=lambda: [SimpleNamespace(type=self.QUIT)])
        self.time = SimpleNamespace(Clock=self._Clock)
        self.font = SimpleNamespace(Font=lambda name, size: self._Font())
        self.draw = self._Draw()

    def init(self) -> None:
        pass

    def quit(self) -> None:
        pass
