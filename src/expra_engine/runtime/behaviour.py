"""Public runtime gameplay behaviour contract and exposed field metadata."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

from expra_engine.runtime.input import ActionEvent, InputMap

if TYPE_CHECKING:
    from expra_engine.core.entity import Entity

C = TypeVar("C")

Signal = Callable[[object], None]
PASS = False
HANDLED = True


@dataclass(frozen=True, slots=True)
class ExposedField:
    """Serializable metadata and validation rules for one Behaviour field."""

    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    tooltip: str = ""
    category: str = ""
    readonly: bool = False
    choices: tuple[object, ...] = ()

    def validate(self, value: object) -> object:
        if isinstance(self.default, bool):
            valid = isinstance(value, bool)
        elif isinstance(self.default, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(self.default, float):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = isinstance(value, type(self.default))
        if not valid:
            raise TypeError(f"expected {type(self.default).__name__}, got {type(value).__name__}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("exposed float must be finite")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and self.minimum is not None
            and value < self.minimum
        ):
            raise ValueError(f"value must be at least {self.minimum!r}")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and self.maximum is not None
            and value > self.maximum
        ):
            raise ValueError(f"value must be at most {self.maximum!r}")
        if self.choices and value not in self.choices:
            raise ValueError(f"value must be one of {self.choices!r}")
        return value


class _ExposedDescriptor:
    def __init__(self, field: ExposedField) -> None:
        self.field = field
        self.name = ""

    def __set_name__(self, owner: type[Behaviour], name: str) -> None:
        self.name = name

    def __get__(self, instance: Behaviour | None, owner: type[Behaviour]) -> Any:
        if instance is None:
            return self
        return instance._exposed_values.get(self.name, self.field.default)

    def __set__(self, instance: Behaviour, value: object) -> None:
        if self.field.readonly and self.name in instance._exposed_values:
            raise AttributeError(f"exposed field {self.name!r} is read-only")
        instance._exposed_values[self.name] = self.field.validate(value)


def exposed(
    default: object,
    *,
    min: float | int | None = None,
    max: float | int | None = None,
    step: float | int | None = None,
    tooltip: str = "",
    category: str = "",
    readonly: bool = False,
    choices: tuple[object, ...] = (),
) -> object:
    """Declare a validated, JSON-compatible inspector field."""
    if default is None:
        raise TypeError("exposed fields require a non-None default")
    try:
        json.dumps(default)
    except (TypeError, ValueError) as exc:
        raise TypeError("exposed default must be JSON-compatible") from exc
    field = ExposedField(default, min, max, step, tooltip, category, readonly, choices)
    field.validate(default)
    return _ExposedDescriptor(field)


@dataclass(slots=True)
class BehaviourContext:
    """Explicit runtime services made available to a live Behaviour."""

    input: InputMap
    engine: object | None = None
    scene: object | None = None
    signal: Signal | None = None


class Behaviour:
    """Base class for an object-owned runtime gameplay behaviour."""

    def __init__(self) -> None:
        self.entity: Entity | None = None
        self._enabled = True
        self._started = False
        self._destroyed = False
        self._system_owned = False
        self._exposed_values: dict[str, object] = {}
        self._context = BehaviourContext(input=InputMap())

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("Behaviour.enabled must be bool")
        if value == self._enabled:
            return
        self._enabled = value
        if self._started:
            (self.on_enabled if value else self.on_disabled)()

    @property
    def input(self) -> InputMap:
        return self._context.input

    @property
    def engine(self) -> object | None:
        return self._context.engine

    @property
    def scene(self) -> object | None:
        return self._context.scene

    def _bind_context(
        self,
        *,
        input_map: InputMap | None,
        engine: object | None,
        scene: object | None,
        signal: Signal | None = None,
    ) -> None:
        self._context = BehaviourContext(input_map or InputMap(), engine, scene, signal)

    def _set_started(self, started: bool) -> None:
        self._started = started

    @classmethod
    def exposed_schema(cls) -> dict[str, ExposedField]:
        """Return inherited exposed fields with deterministic overrides."""
        schema: dict[str, ExposedField] = {}
        for base in reversed(cls.__mro__):
            for name, value in base.__dict__.items():
                if isinstance(value, _ExposedDescriptor):
                    schema[name] = value.field
                elif name in schema and isinstance(value, property):
                    del schema[name]
        return schema

    def get_component(self, cls: type[C]) -> C | None:
        """Return a component from the owning entity, if present."""
        if self.entity is None:
            return None
        return cast(C, self.entity.get_component(cast(Any, cls)))

    def has_component(self, cls: type[C]) -> bool:
        return self.get_component(cls) is not None

    def require_component(self, cls: type[C]) -> C:
        component = self.get_component(cls)
        if component is None:
            entity_name = self.entity.name if self.entity is not None else "unowned"
            raise LookupError(f"{entity_name!r} has no {cls.__name__}")
        return component

    def emit(self, event: object) -> None:
        if self._context.signal is None:
            raise RuntimeError("Behaviour is not running")
        self._context.signal(event)

    def on_attach(self, entity: Entity) -> None:
        """Handle attachment to an entity."""

    def on_start(self) -> None:
        """Handle the start of runtime execution."""

    def on_fixed_update(self, dt: float) -> None:
        """Handle a fixed-timestep simulation update."""

    def on_enabled(self) -> None:
        """Handle a transition from disabled to enabled after start."""

    def on_disabled(self) -> None:
        """Handle a transition from enabled to disabled after start."""

    def on_update(self, dt: Any, signal: Any = None) -> None:
        """Handle a runtime update event."""

    def on_event(self, event: object) -> None:
        """Handle a non-update runtime event when explicitly routed."""

    def on_input(self, event: ActionEvent, signal: Any = None) -> bool:
        """Handle an action event and return whether it was consumed."""
        return False

    def on_stop(self) -> None:
        """Handle the end of runtime execution."""

    def on_detach(self) -> None:
        """Handle detachment from an entity."""

    def on_destroy(self) -> None:
        """Handle one-time runtime destruction."""


BehaviourFactory = Callable[[], Behaviour]


__all__ = [
    "HANDLED",
    "PASS",
    "Behaviour",
    "BehaviourContext",
    "BehaviourFactory",
    "ExposedField",
    "Signal",
    "exposed",
]
