"""Serializable authored Level anchor component data."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from expra_engine.core.component import Component

__all__ = ("LevelAnchorComponent", "LevelAnchorKind", "LevelAnchorShape")


class LevelAnchorKind(StrEnum):
    ENTRANCE = "entrance"
    EXIT = "exit"
    BOTH = "both"


class LevelAnchorShape(StrEnum):
    RECTANGLE = "rectangle"
    CIRCLE = "circle"


class LevelAnchorComponent(Component):
    """A named local-space arrival/exit anchor and optional trigger bounds."""

    component_type = "level_anchor"

    def __init__(
        self,
        anchor_id: object,
        *,
        kind: LevelAnchorKind | str = LevelAnchorKind.BOTH,
        shape: LevelAnchorShape | str = LevelAnchorShape.RECTANGLE,
        size: tuple[float, float] = (1.0, 1.0),
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        if not isinstance(anchor_id, str) or not anchor_id.strip() or anchor_id != anchor_id.strip():
            raise ValueError("anchor_id must be a non-empty trimmed string")
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        try:
            anchor_kind = LevelAnchorKind(kind)
            anchor_shape = LevelAnchorShape(shape)
        except (TypeError, ValueError) as error:
            raise ValueError("Level anchor kind or shape is invalid") from error
        if isinstance(size, (str, bytes)) or len(size) != 2:
            raise ValueError("Level anchor size must contain two positive finite values")
        dimensions = tuple(float(value) for value in size)
        if any(isinstance(value, bool) for value in size) or not all(
            math.isfinite(value) and value > 0.0 for value in dimensions
        ):
            raise ValueError("Level anchor size must contain two positive finite values")
        self.anchor_id = anchor_id
        self.kind = anchor_kind
        self.shape = anchor_shape
        self.size = dimensions

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "anchor_id": self.anchor_id,
            "kind": self.kind.value,
            "shape": self.shape.value,
            "size": list(self.size),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LevelAnchorComponent:
        return cls(
            data.get("anchor_id"),
            kind=data.get("kind", LevelAnchorKind.BOTH),
            shape=data.get("shape", LevelAnchorShape.RECTANGLE),
            size=data.get("size", (1.0, 1.0)),
            enabled=data.get("enabled", True),
        )
