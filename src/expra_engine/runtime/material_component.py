"""Authored component wrapper for renderer-neutral material response data."""

from __future__ import annotations

from typing import Any

from expra_engine.core.component import Component
from expra_engine.runtime.material_lighting import LightingMode, MaterialLightResponse
from expra_engine.runtime.normal_mapping import (
    NormalMapEncoding,
    NormalMapMode,
    NormalYConvention,
    coerce_normal_map_enums,
    validate_normal_strength,
    validate_normal_texture_id,
)
from expra_engine.runtime.rendering import Color, NormalMapDescriptor

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
        normal_map_mode: NormalMapMode | str = NormalMapMode.DISABLED,
        normal_texture_id: str | None = None,
        normal_strength: float = 1.0,
        normal_y_convention: NormalYConvention | str = NormalYConvention.OPENGL,
        normal_encoding: NormalMapEncoding | str = NormalMapEncoding.RGB_XYZ,
    ) -> None:
        super().__init__(enabled=enabled)
        response = MaterialLightResponse(
            mode=mode,
            ambient_response=ambient_response,
            diffuse=diffuse,
            emission=emission,
            emission_color=Color.from_value(emission_color),
            toon_steps=toon_steps,
        )
        self.mode = LightingMode(response.mode).value
        self.ambient_response = response.ambient_response
        self.diffuse = response.diffuse
        self.emission = response.emission
        self.emission_color = response.emission_color
        self.toon_steps = response.toon_steps
        mode, y_convention, encoding = coerce_normal_map_enums(
            normal_map_mode, normal_y_convention, normal_encoding
        )
        texture_id = validate_normal_texture_id(normal_texture_id)
        strength = validate_normal_strength(normal_strength)
        if mode is NormalMapMode.EXPLICIT and texture_id is None:
            raise ValueError("explicit normal mapping requires normal_texture_id")
        self._normal_map_mode = mode.value
        self._normal_texture_id = texture_id
        self._normal_strength = strength
        self._normal_y_convention = y_convention.value
        self._normal_encoding = encoding.value

    @property
    def normal_map_mode(self) -> str:
        return self._normal_map_mode

    @normal_map_mode.setter
    def normal_map_mode(self, value: NormalMapMode | str) -> None:
        try:
            mode = NormalMapMode(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported normal-map mode") from exc
        if mode is NormalMapMode.EXPLICIT and self._normal_texture_id is None:
            raise ValueError("explicit normal mapping requires normal_texture_id")
        self._normal_map_mode = mode.value

    @property
    def normal_texture_id(self) -> str | None:
        return self._normal_texture_id

    @normal_texture_id.setter
    def normal_texture_id(self, value: str | None) -> None:
        texture_id = validate_normal_texture_id(value)
        if self._normal_map_mode == NormalMapMode.EXPLICIT.value and texture_id is None:
            raise ValueError("explicit normal mapping requires normal_texture_id")
        self._normal_texture_id = texture_id

    @property
    def normal_strength(self) -> float:
        return self._normal_strength

    @normal_strength.setter
    def normal_strength(self, value: float) -> None:
        self._normal_strength = validate_normal_strength(value)

    @property
    def normal_y_convention(self) -> str:
        return self._normal_y_convention

    @normal_y_convention.setter
    def normal_y_convention(self, value: NormalYConvention | str) -> None:
        try:
            self._normal_y_convention = NormalYConvention(value).value
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported normal-map Y convention") from exc

    @property
    def normal_encoding(self) -> str:
        return self._normal_encoding

    @normal_encoding.setter
    def normal_encoding(self, value: NormalMapEncoding | str) -> None:
        try:
            self._normal_encoding = NormalMapEncoding(value).value
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported normal-map encoding") from exc

    @property
    def emission_color(self) -> Color:
        return self._emission_color

    @emission_color.setter
    def emission_color(self, value: Color | tuple[float, ...] | list[float]) -> None:
        self._emission_color = Color.from_value(value)

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

    @property
    def normal_map_descriptor(self) -> NormalMapDescriptor | None:
        if self.normal_map_mode == NormalMapMode.DISABLED.value:
            return None
        return NormalMapDescriptor(
            mode=self.normal_map_mode,
            texture_id=self.normal_texture_id,
            strength=self.normal_strength,
            y_convention=self.normal_y_convention,
            encoding=self.normal_encoding,
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
            "emission_color": response.emission_color.to_list(),
            "toon_steps": response.toon_steps,
            "normal_map_mode": self.normal_map_mode,
            "normal_texture_id": self.normal_texture_id,
            "normal_strength": self.normal_strength,
            "normal_y_convention": self.normal_y_convention,
            "normal_encoding": self.normal_encoding,
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
            normal_map_mode=data.get("normal_map_mode", NormalMapMode.DISABLED.value),
            normal_texture_id=data.get("normal_texture_id"),
            normal_strength=data.get("normal_strength", 1.0),
            normal_y_convention=data.get("normal_y_convention", NormalYConvention.OPENGL.value),
            normal_encoding=data.get("normal_encoding", NormalMapEncoding.RGB_XYZ.value),
        )
