"""Standard standalone runner for a project directory."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.pygame_renderer import (
    PygameRenderer,
    PygameRenderFrame,
    PygameResourceProvider,
)
from expra_engine.runtime.pygame_runtime import PygameRuntime
from expra_engine.runtime.render_extractor import extract_render_frame
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
    renderer = PygameRenderer(
        pygame,
        None,
        screen_size=(960, 640),
        resource_provider=PygameResourceProvider(pygame, project.resource_service()),
    )

    def frame_factory(current_engine: Engine, dt: float) -> RenderFrame:
        extracted = (
            extract_render_frame(
                current_engine.active_scene,
                elapsed=dt,
                interpolator=current_engine.transform_interpolator,
                interpolation_fraction=current_engine.interpolation_fraction,
                animated_players=current_engine.animated_sprite_system.players,
            )
            if current_engine.active_scene is not None
            else RenderFrame(elapsed=dt)
        )
        return RenderFrame(
            extracted.items,
            elapsed=dt,
            payload=PygameRenderFrame(
                active_scene=current_engine.active_scene,
                interpolator=current_engine.transform_interpolator,
                interpolation_fraction=current_engine.interpolation_fraction,
                modulation=extracted.modulation,
            ),
            submissions=extracted.submissions,
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
