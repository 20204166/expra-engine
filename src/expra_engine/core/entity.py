"""Entity — a named game object with components.

Entities have stable UUIDs, a name, an enabled flag, and an ordered list of
components. Hierarchy (parent/child) is supported via optional parent_id.
"""

from __future__ import annotations

import inspect
import uuid
from typing import TYPE_CHECKING, Any, TypeVar

from expra_engine.core.component import (
    Component,
    OpaqueComponent,
    component_from_dict,
    registered_component_types,
)

if TYPE_CHECKING:
    from expra_engine.runtime.behaviour import Behaviour, BehaviourFactory
    from expra_engine.runtime.events import Update
    from expra_engine.runtime.input import ActionEvent

C = TypeVar("C", bound=Component)


class Entity:
    """A named game object that holds components.

    ``entity_id`` is a stable UUID string. IDs survive serialization
    round-trips; never regenerate them on load.
    """

    def __init__(
        self,
        name: str,
        *,
        entity_id: str | None = None,
        enabled: bool = True,
        layer: int = 0,
        parent_id: str | None = None,
    ) -> None:
        self.entity_id: str = entity_id or str(uuid.uuid4())
        self.name = name
        self.enabled = enabled
        self.layer = layer
        self.parent_id = parent_id
        self._components: list[Component] = []
        self._behaviours: list[Behaviour] = []
        self._behaviour_factories: list[BehaviourFactory] = []
        self._tags: set[str] = set()

    @property
    def components(self) -> tuple[Component, ...]:
        return tuple(self._components)

    def add_component(self, component: Component) -> None:
        self._components.append(component)

    def remove_component(self, component: Component) -> bool:
        try:
            self._components.remove(component)
            return True
        except ValueError:
            return False

    def get_component(self, cls: type[C]) -> C | None:
        for component in self._components:
            if isinstance(component, cls):
                return component
        return None

    def get_components(self, cls: type[C]) -> list[C]:
        return [c for c in self._components if isinstance(c, cls)]

    @property
    def behaviours(self) -> tuple[Behaviour, ...]:
        """Return attached runtime behaviours in insertion order."""
        return tuple(self._behaviours)

    def add_behaviour(self, behaviour: Behaviour, *, runtime_factory: BehaviourFactory) -> None:
        """Attach an unowned runtime behaviour to this entity."""
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if behaviour.entity is not None:
            raise ValueError("behaviour is already owned by an entity")

        self._behaviours.append(behaviour)
        self._behaviour_factories.append(runtime_factory)
        behaviour.entity = self
        behaviour.on_attach(self)

    def remove_behaviour(self, behaviour: Behaviour) -> bool:
        """Detach a behaviour, returning whether it was attached."""
        try:
            index = self._behaviours.index(behaviour)
        except ValueError:
            return False

        self._behaviours.pop(index)
        self._behaviour_factories.pop(index)
        try:
            behaviour.on_detach()
        finally:
            behaviour.entity = None
        return True

    def get_behaviour(self, cls: type[Behaviour]) -> Behaviour | None:
        """Return the first attached behaviour matching ``cls``."""
        for behaviour in self._behaviours:
            if isinstance(behaviour, cls):
                return behaviour
        return None

    def on_update(self, event: Update, signal: Any) -> None:
        """Dispatch an update to the currently eligible behaviours."""
        for behaviour in tuple(self._behaviours):
            if (
                not self.enabled
                or behaviour.entity is not self
                or not behaviour.enabled
                or getattr(behaviour, "_system_owned", False)
            ):
                continue
            method = behaviour.on_update
            try:
                inspect.signature(method).bind(event, signal)
            except TypeError:
                fixed = getattr(behaviour, "on_fixed_update", None)
                if fixed is not None:
                    fixed(event.time_delta)
            else:
                method(event, signal)

    def on_frame_update(self, event: Any, signal: Any) -> None:
        """Dispatch a variable frame update to modern behaviours."""
        for behaviour in tuple(self._behaviours):
            if (
                not self.enabled
                or behaviour.entity is not self
                or not behaviour.enabled
                or getattr(behaviour, "_system_owned", False)
            ):
                continue
            method = behaviour.on_update
            try:
                inspect.signature(method).bind(event.time_delta)
            except TypeError:
                continue
            method(event.time_delta)

    def on_action_event(self, event: ActionEvent, signal: Any) -> bool:
        """Dispatch input until an eligible behaviour consumes it."""
        for behaviour in tuple(self._behaviours):
            if (
                not self.enabled
                or behaviour.entity is not self
                or not behaviour.enabled
                or getattr(behaviour, "_system_owned", False)
            ):
                continue
            method = behaviour.on_input
            try:
                inspect.signature(method).bind(event)
            except TypeError:
                handled = method(event, signal)
            else:
                handled = method(event)
            if handled:
                return True
        return False

    @property
    def tags(self) -> frozenset[str]:
        """The set of tags on this entity (immutable view)."""
        return frozenset(self._tags)

    def add_tag(self, tag: str) -> None:
        """Add a tag to this entity."""
        self._tags.add(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag; no-op if absent."""
        self._tags.discard(tag)

    def has_tag(self, tag: str) -> bool:
        """Return True if this entity has the given tag."""
        return tag in self._tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "enabled": self.enabled,
            "layer": self.layer,
            "parent_id": self.parent_id,
            "components": [c.to_dict() for c in self._components],
            "tags": sorted(self._tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, include_components: bool = True) -> Entity:
        entity = cls(
            name=str(data["name"]),
            entity_id=str(data["entity_id"]),
            enabled=bool(data.get("enabled", True)),
            layer=int(data.get("layer", 0)),
            parent_id=data.get("parent_id"),
        )
        for tag in data.get("tags", []):
            entity.add_tag(str(tag))
        if include_components:
            entity._restore_components(data)
        return entity

    def _restore_components(self, data: dict[str, Any]) -> None:
        components = data.get("components", [])
        if not isinstance(components, list):
            raise ValueError("entity components must be a list")
        for component_data in components:
            if not isinstance(component_data, dict):
                raise ValueError("entity component must be an object")
            try:
                self.add_component(component_from_dict(component_data))
            except (TypeError, ValueError, KeyError):
                component_type = component_data.get("type")
                if not isinstance(component_type, str):
                    raise
                if component_type in {
                    name for name, _component_cls in registered_component_types()
                }:
                    raise
                self.add_component(OpaqueComponent(component_data))

    def __repr__(self) -> str:
        return f"Entity({self.name!r}, id={self.entity_id!r})"
