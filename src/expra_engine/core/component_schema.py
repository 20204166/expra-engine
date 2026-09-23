"""Immutable metadata used by editor component authoring."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PropertyDescriptor:
    name: str
    label: str
    value_type: type
    default: Any
    editable: bool = True
    enum_values: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    tuple_length: int | None = None
    tuple_minimum: tuple[float, ...] | None = None
    tuple_integer: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "enum_values", tuple(self.enum_values))

    def convert(self, value: Any, *, original: Any = None) -> Any:
        """Convert an editor value, returning the existing value if invalid."""
        fallback = self.default if original is None else original
        if not self.editable:
            return fallback
        try:
            converted: Any
            if self.value_type is bool:
                if isinstance(value, bool):
                    converted = value
                elif str(value).strip().lower() in {"true", "1", "yes", "on"}:
                    converted = True
                elif str(value).strip().lower() in {"false", "0", "no", "off"}:
                    converted = False
                else:
                    return fallback
            elif self.value_type is tuple:
                converted = tuple(float(part.strip()) for part in str(value).split(","))
                if (
                    not converted
                    or not all(math.isfinite(part) for part in converted)
                    or (self.tuple_integer and not all(part.is_integer() for part in converted))
                    or (self.tuple_length is not None and len(converted) != self.tuple_length)
                    or (
                        self.tuple_minimum is not None
                        and (
                            len(converted) != len(self.tuple_minimum)
                            or any(
                                part < minimum
                                for part, minimum in zip(converted, self.tuple_minimum, strict=True)
                            )
                        )
                    )
                ):
                    return fallback
            elif hasattr(self.value_type, "from_dict"):
                raw = json.loads(value) if isinstance(value, str) else value
                if not isinstance(raw, Mapping):
                    return fallback
                converted = self.value_type.from_dict(raw)
            else:
                converted = self.value_type(value)
            if isinstance(converted, (int, float)) and not isinstance(converted, bool):
                if not math.isfinite(converted):
                    return fallback
                if self.minimum is not None and converted < self.minimum:
                    return fallback
                if self.maximum is not None and converted > self.maximum:
                    return fallback
            if self.enum_values and converted not in self.enum_values:
                return fallback
            return converted
        except (TypeError, ValueError, OverflowError):
            return fallback


@dataclass(frozen=True)
class ComponentTypeSpec:
    name: str
    cls: type
    fields: tuple[PropertyDescriptor, ...] = ()
    required_types: tuple[type, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "required_types", tuple(self.required_types))


_COMPONENT_SPECS: dict[str, ComponentTypeSpec] = {}


def register_component_spec(spec: ComponentTypeSpec) -> None:
    _COMPONENT_SPECS[spec.name] = spec


def component_type_spec(name: str) -> ComponentTypeSpec:
    try:
        return _COMPONENT_SPECS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown component type: {name!r}") from exc


def registered_component_specs() -> tuple[ComponentTypeSpec, ...]:
    return tuple(_COMPONENT_SPECS.values())
