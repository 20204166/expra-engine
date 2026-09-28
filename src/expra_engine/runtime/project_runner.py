"""Standard standalone runner for a project directory."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.engine import Engine
from expra_engine.core.project import Project, ProjectError
from expra_engine.core.scene import Scene
from expra_engine.core.world import World
from expra_engine.messages import project as project_messages
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.normal_mapping import NormalMapResolver
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
    """Run the configured Scene, Level, or World entrypoint in a standalone process."""
    import pygame  # type: ignore[reportMissingImports]

    project = Project.load(Path(project_dir))
    observer = ObservabilityWatcher()
    engine = Engine(observer=observer)
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    document = project.load_document(observer=observer)
    if isinstance(document, World):
        engine.set_world(
            document,
            project=project,
            world_resource_path=project.entrypoint,
        )
    elif isinstance(document, Scene):
        engine.set_scene(document)
    else:
        raise ProjectError(project_messages.project_entrypoint_document_unsupported())
    resources = project.resource_service(observer=observer)
    renderer = PygameRenderer(
        pygame,
        None,
        screen_size=(960, 640),
        resource_provider=PygameResourceProvider(pygame, resources),
        normal_map_resolver=NormalMapResolver(resources),
        observer=observer,
    )

    def frame_factory(current_engine: Engine, dt: float) -> RenderFrame:
        world_system = (
            current_engine.world_streaming_system
            if current_engine.active_scene is not None
            else None
        )
        if world_system is not None and world_system.startup_error is not None:
            raise RuntimeError(world_system.startup_error)
        extracted = (
            extract_render_frame(
                current_engine.active_scene,
                elapsed=dt,
                interpolator=current_engine.transform_interpolator,
                interpolation_fraction=current_engine.interpolation_fraction,
                animated_players=current_engine.animated_sprite_system.players,
                modulation_entity_ids=(
                    world_system.environment_entity_ids if world_system is not None else None
                ),
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
            lights=extracted.lights,
            lighting_enabled=extracted.lighting_enabled,
        )

    runtime = PygameRuntime(
        engine,
        renderer,
        pygame_module=pygame,
        size=(960, 640),
        frame_factory=frame_factory,
    )
    world_system = engine.world_streaming_system
    try:
        if not engine.play():
            raise RuntimeError(project_messages.project_engine_could_not_play())
        runtime.run()
    finally:
        if engine.run_state.value != "edit":
            engine.stop()
        if world_system is not None:
            world_system.close()


__all__ = ["run_project"]
