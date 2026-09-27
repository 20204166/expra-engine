"""Authored component wrapper for renderer-neutral material response data."""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.material_lighting import LightingMode, MaterialLightResponse
from expra_engine.runtime.rendering import Color

__all__ = ("MaterialComponent",)

_WHITE = Color(1.0, 1.0, 1.0, 1.0)


class MaterialComponent(Component):
    """One material response shared by an entity's rendered visuals."""

    component_type = "material"

    def __init__(
        self,
        mode: LightingMode | str = LightingMode.LIT,
        ambient_response: float = 1.0,
        diffuse: float = 1.0,
        emission: float = 0.0,
        emission_color: Color | tuple[float, ...] | list[float] = _WHITE,
        toon_steps: int = 3,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        response = MaterialLightResponse(
            mode=mode,
            ambient_response=ambient_response,
            diffuse=diffuse,
            emission=emission,
            emission_color=(
                emission_color if isinstance(emission_color, Color) else Color(*emission_color)
            ),
            toon_steps=toon_steps,
        )
        self.mode = LightingMode(response.mode).value
        self.ambient_response = response.ambient_response
        self.diffuse = response.diffuse
        self.emission = response.emission
        self.emission_color = response.emission_color
        self.toon_steps = response.toon_steps

    @property
    def emission_color(self) -> Color:
        return self._emission_color

    @emission_color.setter
    def emission_color(self, value: Color | tuple[float, ...] | list[float]) -> None:
        self._emission_color = value if isinstance(value, Color) else Color(*value)

    @property
    def response(self) -> MaterialLightResponse:
        return MaterialLightResponse(
            mode=self.mode,
            ambient_response=self.ambient_response,
            diffuse=self.diffuse,
            emission=self.emission,
            emission_color=self.emission_color,
            toon_steps=self.toon_steps,
        )

    def to_dict(self) -> dict[str, Any]:
        response = self.response
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "mode": LightingMode(response.mode).value,
            "ambient_response": response.ambient_response,
            "diffuse": response.diffuse,
            "emission": response.emission,
            "emission_color": [
                response.emission_color.red,
                response.emission_color.green,
                response.emission_color.blue,
                response.emission_color.alpha,
            ],
            "toon_steps": response.toon_steps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialComponent:
        return cls(
            mode=data.get("mode", LightingMode.LIT.value),
            ambient_response=data.get("ambient_response", 1.0),
            diffuse=data.get("diffuse", 1.0),
            emission=data.get("emission", 0.0),
            emission_color=data.get("emission_color", (1.0, 1.0, 1.0, 1.0)),
            toon_steps=data.get("toon_steps", 3),
            enabled=bool(data.get("enabled", True)),
        )
