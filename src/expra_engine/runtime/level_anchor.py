"""Serializable named entrances/exits attached to ordinary Level entities."""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import Component
from expra_engine.core.level_anchor import LevelAnchorComponent, LevelAnchorKind, LevelAnchorShape

__all__ = (
    "LevelAnchorComponent",
    "LevelAnchorKind",
    "LevelAnchorShape",
    "StreamingAnchorComponent",
    "WorldPersistentActorComponent",
)


class StreamingAnchorComponent(Component):
    """Explicitly nominate an ordinary Entity as a World residency anchor."""

    component_type = "streaming_anchor"

    def __init__(self, anchor_id: object, *, enabled: bool = True) -> None:
        super().__init__(enabled=enabled)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if not isinstance(anchor_id, str) or not anchor_id.strip() or anchor_id != anchor_id.strip():
            raise ValueError("streaming anchor_id must be a non-empty trimmed string")
        self.anchor_id = anchor_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "anchor_id": self.anchor_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamingAnchorComponent:
        return cls(data.get("anchor_id"), enabled=data.get("enabled", True))


class WorldPersistentActorComponent(Component):
    """Explicitly transfer an authored Entity's runtime lifetime to its World."""

    component_type = "world_persistent_actor"

    def __init__(self, persistent_id: object, *, enabled: bool = True) -> None:
        super().__init__(enabled=enabled)
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if (
            not isinstance(persistent_id, str)
            or not persistent_id.strip()
            or persistent_id != persistent_id.strip()
        ):
            raise ValueError("persistent_id must be a non-empty trimmed string")
        self.persistent_id = persistent_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "persistent_id": self.persistent_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldPersistentActorComponent:
        return cls(data.get("persistent_id"), enabled=data.get("enabled", True))
