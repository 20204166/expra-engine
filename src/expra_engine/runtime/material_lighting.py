"""Backend-neutral response settings for 2D material lighting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from expra_engine.runtime.rendering import Color

__all__ = ("LightingMode", "MaterialLightResponse")


class LightingMode(StrEnum):
    LIT = "lit"
    UNLIT = "unlit"
    TOON = "toon"


@dataclass(frozen=True)
class MaterialLightResponse:
    """Portable 2D lighting response; backend execution stays renderer-owned.

    Canonical composition is: apply ambient modulation scaled by
    ``ambient_response``, add local diffuse light scaled by ``diffuse`` (toon
    mode quantizes each light's falloff before lights are summed), modulate the
    visual's source pixels, then add ``emission_color`` scaled by ``emission``
    from the unlit source. Unlit mode skips ambient and local light but retains
    source color and emission. Emission never enters the scene's Light2D list.
    """

    mode: LightingMode | str = LightingMode.LIT
    ambient_response: float = 1.0
    diffuse: float = 1.0
    emission: float = 0.0
    emission_color: Color = field(default_factory=lambda: Color(1.0, 1.0, 1.0, 1.0))
    toon_steps: int = 3

    def __post_init__(self) -> None:
        try:
            mode = self.mode if isinstance(self.mode, LightingMode) else LightingMode(self.mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported material lighting mode") from exc
        object.__setattr__(self, "mode", mode)
        for name in ("ambient_response", "diffuse", "emission"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        if not isinstance(self.emission_color, Color):
            raise TypeError("emission_color must be rendering.Color")
        steps = int(self.toon_steps)
        if steps != self.toon_steps or not 2 <= steps <= 8:
            raise ValueError("toon_steps must be an integer between 2 and 8")
        object.__setattr__(self, "toon_steps", steps)

    @property
    def receives_light(self) -> bool:
        return self.mode is not LightingMode.UNLIT
