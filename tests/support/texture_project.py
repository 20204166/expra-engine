"""Project-independent real-texture fixture factory."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.runtime.visual_components import SpriteComponent

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "texture_probe.png"


def make_texture_project(tmp_path: Path) -> tuple[Project, Scene, str]:
    """Create a normal project containing one origin-centered real PNG sprite."""
    project = Project.create("Texture Probe", tmp_path / "texture-probe")
    asset_id = project.import_asset(_FIXTURE, "probe.png")
    scene = Scene("Probe")
    entity = scene.create_entity("probe", entity_id="probe")
    entity.add_component(SpriteComponent(str(asset_id), width=2.0, height=2.0))
    project.save_scene(scene)
    return project, scene, str(asset_id)
