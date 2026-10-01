"""Authored viewport anchor for camera-mounted visual hierarchies."""

from __future__ import annotations

from expra_engine.core.component import Component
from expra_engine.core.math_utils import finite_float

VIEWPORT_ANCHORS = {
    "top_left": (0.0, 1.0),
    "top_center": (0.5, 1.0),
    "top_right": (1.0, 1.0),
    "center_left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "center_right": (1.0, 0.5),
    "bottom_left": (0.0, 0.0),
    "bottom_center": (0.5, 0.0),
    "bottom_right": (1.0, 0.0),
}
VIEWPORT_MOUNTS = tuple(VIEWPORT_ANCHORS)


class CameraMountComponent(Component):
    """Attach a viewport anchor and logical-pixel offset to a HUD root."""

    component_type = "camera_mount"

    def __init__(
        self,
        mount: str = "top_left",
        *,
        x: float = 0.0,
        y: float = 0.0,
        enabled: bool = True,
    ) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        super().__init__(enabled=enabled)
        if mount not in VIEWPORT_MOUNTS:
            raise ValueError(f"mount must be one of {VIEWPORT_MOUNTS!r}")
        self.mount = mount
        if isinstance(x, bool) or isinstance(y, bool):
            raise ValueError("mount offsets must be numeric finite values")
        self.x = finite_float(x, "x")
        self.y = finite_float(y, "y")

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "mount": self.mount,
            "x": self.x,
            "y": self.y,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CameraMountComponent:
        return cls(
            mount=str(data.get("mount", "top_left")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            enabled=bool(data.get("enabled", True)),
        )


__all__ = ["VIEWPORT_ANCHORS", "VIEWPORT_MOUNTS", "CameraMountComponent"]
