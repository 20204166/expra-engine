"""Standalone Space Pong launcher using the standard Pygame runtime path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.pygame_runtime import PygameRuntime
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.script_registry import ScriptRegistry


PROJECT_DIR = Path(__file__).resolve().parent


def create_runtime(pygame_module: Any) -> PygameRuntime:
    project = Project.load(PROJECT_DIR)
    engine = Engine()
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(project.load_scene())
    renderer = PygameRenderer(pygame_module, None, screen_size=(960, 640))
    engine.play()
    behaviour = engine.behaviour_system.instances[0]
    return PygameRuntime(
        engine,
        renderer,
        pygame_module=pygame_module,
        size=(960, 640),
        camera=__import__("expra_engine.runtime.rendering", fromlist=["OrthographicCamera"]).OrthographicCamera(width=100.0, height=60.0),
        ui_root=behaviour.ui,
        frame_factory=lambda current, dt: extract_render_frame(current.active_scene, elapsed=dt),
    )


def main() -> None:
    import pygame

    create_runtime(pygame).run()


if __name__ == "__main__":
    main()
