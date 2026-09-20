"""Standard standalone runner for a project directory."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameRenderFrame
from expra_engine.runtime.pygame_runtime import PygameRuntime
from expra_engine.runtime.rendering import RenderFrame
from expra_engine.runtime.script_registry import ScriptRegistry


def run_project(project_dir: Path | str = ".") -> None:
    """Run the configured start scene through the normal Pygame runtime."""
    import pygame  # type: ignore[reportMissingImports]

    project = Project.load(Path(project_dir))
    engine = Engine()
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(project.load_scene())
    renderer = PygameRenderer(pygame, None, screen_size=(960, 640))

    def frame_factory(current_engine: Engine, dt: float) -> RenderFrame:
        return RenderFrame(
            elapsed=dt,
            payload=PygameRenderFrame(active_scene=current_engine.active_scene),
        )

    runtime = PygameRuntime(
        engine,
        renderer,
        pygame_module=pygame,
        size=(960, 640),
        frame_factory=frame_factory,
    )
    engine.play()
    runtime.run()


__all__ = ["run_project"]
