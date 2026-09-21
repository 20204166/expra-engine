"""Launch Neon Arena with the Pygame runtime and renderer."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime import (
    PygameRenderer,
    PygameRenderFrame,
    PygameRuntime,
    RenderContractFrame,
    ScriptRegistry,
)
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.render_extractor import extract_render_frame

if __package__:
    from .game import NeonArenaGame, load_scene
else:  # Running the exported entrypoint as a script.
    from game import NeonArenaGame, load_scene


@dataclass(frozen=True)
class SmokeConfig:
    frame_limit: int
    report_path: Path


def smoke_config_from_environment(project_dir: Path) -> SmokeConfig | None:
    """Read the opt-in bounded-run configuration used by export smoke tests."""
    raw_frames = os.environ.get("EXPRA_SMOKE_FRAMES")
    if raw_frames is None:
        return None
    try:
        frame_limit = int(raw_frames)
    except ValueError as exc:
        raise ValueError("EXPRA_SMOKE_FRAMES must be a positive integer") from exc
    if frame_limit <= 0:
        raise ValueError("EXPRA_SMOKE_FRAMES must be a positive integer")
    report = os.environ.get("EXPRA_SMOKE_REPORT", "smoke_report.json")
    report_path = Path(report)
    if not report_path.is_absolute():
        report_path = project_dir / report_path
    return SmokeConfig(frame_limit, report_path)


def _write_smoke_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _configure_scripted_input(engine: Engine, project: Any) -> None:
    """Map the original physical controls to semantic project actions."""
    settings = project.input_settings or {
        "move_left": "keyboard:left",
        "move_right": "keyboard:right",
        "move_up": "keyboard:up",
        "move_down": "keyboard:down",
        "restart": "keyboard:r",
    }
    for action, physical in settings.items():
        _, control = physical.split(":", 1)
        engine.input_map.bind(ActionId(action), PhysicalInput("keyboard", control))


def _scripted_state(engine: Engine) -> tuple[int, str]:
    """Read renderer state from the project controller without engine coupling."""
    for behaviour in engine.behaviour_system.instances:
        if behaviour.__class__.__name__ == "GameController":
            return int(getattr(behaviour, "score", 0)), str(getattr(behaviour, "status", ""))
    return 0, ""


def main() -> None:
    project_dir = Path(__file__).parent
    smoke_enabled = "EXPRA_SMOKE_FRAMES" in os.environ
    report_path = Path(os.environ.get("EXPRA_SMOKE_REPORT", "smoke_report.json"))
    if not report_path.is_absolute():
        report_path = project_dir / report_path
    report: dict[str, Any] = {
        "completed": False,
        "frames_rendered": 0,
        "frames_updated": 0,
        "runtime_started": False,
    }
    try:
        smoke = smoke_config_from_environment(project_dir)
        if smoke is not None:
            report["frame_limit"] = smoke.frame_limit
            report_path = smoke.report_path
        pygame = importlib.import_module("pygame")
        pygame.init()
        mode = os.environ.get("EXPRA_NEON_MODE", "legacy").lower()
        if mode not in {"legacy", "scripted"}:
            raise ValueError("EXPRA_NEON_MODE must be legacy or scripted")
        project = Project.load(project_dir)
        engine = Engine()
        engine.set_project(project)
        engine.set_scene(
            load_scene(
                project_dir / "scenes" / ("scripted.json" if mode == "scripted" else "main.json")
            )
        )
        renderer = PygameRenderer(
            pygame,
            None,
            world_bounds=(0, 0, 100, 100),
            arena_bounds=(0, 0, 800, 600),
        )
        runtime = PygameRuntime(
            engine,
            renderer=renderer,
            pygame_module=pygame,
            surface_factory=pygame.display.set_mode,
            size=(800, 600),
        )
        game: NeonArenaGame | None = None
        if mode == "scripted":
            engine.set_script_registry(ScriptRegistry(project.path))
            _configure_scripted_input(engine, project)
        else:
            game = NeonArenaGame(
                runtime,
                left_key=pygame.K_LEFT,
                right_key=pygame.K_RIGHT,
                up_key=pygame.K_UP,
                down_key=pygame.K_DOWN,
                restart_key=pygame.K_r,
            )
        report["runtime_started"] = True

        def frame_factory(current_engine: Any, elapsed: float) -> RenderContractFrame:
            report["frames_updated"] += 1
            report["frames_rendered"] += 1
            if smoke is not None and report["frames_rendered"] >= smoke.frame_limit:
                runtime.stop()
            return RenderContractFrame(
                elapsed=elapsed,
                payload=PygameRenderFrame(
                    current_engine.active_scene,
                    score=game.score if game is not None else _scripted_state(current_engine)[0],
                    status=game.status if game is not None else _scripted_state(current_engine)[1],
                    interpolator=current_engine.transform_interpolator,
                    interpolation_fraction=current_engine.interpolation_fraction,
                    modulation=extract_render_frame(current_engine.active_scene).modulation,
                ),
            )

        runtime.frame_factory = frame_factory
        if game is not None:
            engine.add_system(game)
        engine.play()
        runtime.run()
        if smoke is not None:
            if mode == "scripted":
                report["score"], report["status"] = _scripted_state(engine)
            elif game is not None:
                report["score"] = game.score
                report["status"] = game.status
            report["completed"] = report["frames_rendered"] == smoke.frame_limit
            if not report["completed"]:
                raise RuntimeError("smoke run stopped before the requested frame count")
    except Exception as exc:
        if smoke_enabled:
            report["error"] = str(exc)
        raise
    finally:
        if smoke_enabled:
            _write_smoke_report(report_path, report)


if __name__ == "__main__":
    main()
