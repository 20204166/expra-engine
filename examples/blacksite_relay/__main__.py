"""Standalone launcher for Blacksite Relay."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.pygame_runtime import PygameRuntime
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import OrthographicCamera
from expra_engine.runtime.script_registry import ScriptRegistry
PROJECT_DIR=Path(__file__).resolve().parent

# Per-level scene shorthands for the CLI launcher. The runtime camera itself
# needs no per-level branching: each scene's own "camera" JSON block is
# applied automatically by PygameRuntime._sync_camera_target() on load, so
# the follow/limit/width choices baked into level_02_deepcore.json take
# effect without any code here reading which level is active.
LEVEL_SCENES={'main':'levels/main.level.pb','level2':'levels/level_02_deepcore.level.pb','deepcore':'levels/level_02_deepcore.level.pb'}

def create_runtime(pygame_module: Any, scene_path: str | None = None) -> PygameRuntime:
    project=Project.load(PROJECT_DIR); engine=Engine(); engine.set_project(project); engine.set_script_registry(ScriptRegistry(project.path)); engine.set_scene(project.load_document(scene_path)); renderer=PygameRenderer(pygame_module,None,screen_size=(1100,700),resource_provider=PygameResourceProvider(pygame_module,project.resource_service())); engine.play()
    return PygameRuntime(engine,renderer,pygame_module=pygame_module,size=(1100,700),camera=OrthographicCamera(width=88.0,height=49.5),camera_target_id=None,frame_factory=lambda current,dt: extract_render_frame(current.active_scene,elapsed=dt,interpolator=current.transform_interpolator,interpolation_fraction=current.interpolation_fraction,animated_players=current.animated_sprite_system.players))

def main():
    import pygame
    requested=sys.argv[1] if len(sys.argv)>1 else 'main'
    scene_path=LEVEL_SCENES.get(requested)
    if scene_path is None:
        raise SystemExit(f"unknown level {requested!r}; choose one of {sorted(set(LEVEL_SCENES))}")
    create_runtime(pygame,scene_path).run()
if __name__=='__main__': main()
