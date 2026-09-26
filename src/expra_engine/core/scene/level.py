"""Level — a playable spatial document reusing the Scene entity graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene.scene import Scene

__all__ = ("Level", "LevelMetadata")


@dataclass(frozen=True)
class LevelMetadata:
    """Whole-level semantics only; entity/component state lives in the graph.

    These are the sanctioned level-scoped fields. Lists of enemies, walls,
    pickups, doors, etc. remain ordinary entities/components, never metadata.
    """

    display_name: str | None = None
    world_bounds: tuple[float, float, float, float] | None = None
    spawn_entity_id: str | None = None
    default_camera_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "world_bounds": list(self.world_bounds) if self.world_bounds is not None else None,
            "spawn_entity_id": self.spawn_entity_id,
            "default_camera_id": self.default_camera_id,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LevelMetadata:
        bounds = data.get("world_bounds")
        return cls(
            display_name=data.get("display_name"),
            world_bounds=tuple(bounds) if bounds else None,
            spawn_entity_id=data.get("spawn_entity_id"),
            default_camera_id=data.get("default_camera_id"),
            tags=tuple(data.get("tags", ())),
        )


class Level(Scene):
    """A playable spatial document built on the ordinary Scene entity graph.

    A Level is a Scene (not a parallel world model): it reuses entities,
    hierarchy, transforms, components, selection, commands, rendering, physics,
    animation, behaviour and audio. The only additions are the LEVEL document
    kind and a small ``LevelMetadata`` payload. No ``LevelEntity``,
    ``LevelComponent``, or ``LevelHierarchy`` types exist.
    """

    document_kind = DocumentKind.LEVEL

    def __init__(
        self,
        name: str,
        *,
        scene_id: str | None = None,
        camera: dict[str, Any] | Any | None = None,
        level_metadata: LevelMetadata | None = None,
    ) -> None:
        super().__init__(name, scene_id=scene_id, camera=camera)
        self.level_metadata = level_metadata if level_metadata is not None else LevelMetadata()

    def to_dict(self, *, include_instance_content: bool = True) -> dict[str, Any]:
        data = super().to_dict(include_instance_content=include_instance_content)
        data["kind"] = self.document_kind.value
        data["level_metadata"] = self.level_metadata.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Level:
        level = cast(Level, super().from_dict(data))
        level.level_metadata = LevelMetadata.from_dict(data.get("level_metadata", {}))
        return level
