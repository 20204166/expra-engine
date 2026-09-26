"""Scene data and camera math owned by the core scene package."""

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene.camera import Camera2D, SceneCamera
from expra_engine.core.scene.level import Level, LevelMetadata
from expra_engine.core.scene.scene import Scene
from expra_engine.core.scene.scene_instance import (
    SceneInstanceComponent,
    SceneInstanceCycleError,
    SceneInstanceSourceError,
    resolve_scene_instances,
)

__all__ = (
    "Camera2D",
    "DocumentKind",
    "Level",
    "LevelMetadata",
    "Scene",
    "SceneCamera",
    "SceneInstanceComponent",
    "SceneInstanceCycleError",
    "SceneInstanceSourceError",
    "resolve_scene_instances",
)
