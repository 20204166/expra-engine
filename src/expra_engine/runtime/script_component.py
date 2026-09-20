"""Serialized configuration for one project Behaviour."""

from __future__ import annotations

import json
import keyword
from typing import Any

from expra_engine.core.component import Component
from expra_engine.filesystem import ResourceId


class ScriptComponent(Component):
    """Data-only script identity and exposed values attached to an Entity."""

    component_type = "script"

    def __init__(
        self,
        script_id: ResourceId | str,
        behaviour_class: str,
        *,
        enabled: bool = True,
        exposed_values: dict[str, Any] | None = None,
        order: int = 0,
    ) -> None:
        super().__init__(enabled=enabled)
        self.script_id = (
            script_id if isinstance(script_id, ResourceId) else ResourceId.parse(script_id)
        )
        if (
            not behaviour_class
            or not behaviour_class.isidentifier()
            or keyword.iskeyword(behaviour_class)
        ):
            raise ValueError(f"invalid Behaviour class name: {behaviour_class!r}")
        self.behaviour_class = behaviour_class
        self.exposed_values = dict(exposed_values or {})
        try:
            json.dumps(self.exposed_values)
        except (TypeError, ValueError) as exc:
            raise ValueError("exposed values must be JSON-serializable") from exc
        self.order = int(order)
        self._extra: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        data = {
            "type": self.component_type,
            "enabled": self.enabled,
            "script_id": str(self.script_id),
            "behaviour_class": self.behaviour_class,
            "exposed_values": dict(self.exposed_values),
            "order": self.order,
        }
        data.update(self._extra)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScriptComponent:
        component = cls(
            data["script_id"],
            str(data["behaviour_class"]),
            enabled=data.get("enabled", True),
            exposed_values=dict(data.get("exposed_values", {})),
            order=int(data.get("order", 0)),
        )
        component._extra = {
            key: value
            for key, value in data.items()
            if key
            not in {"type", "enabled", "script_id", "behaviour_class", "exposed_values", "order"}
        }
        return component


class UnresolvedScriptComponent(Component):
    """Preserve invalid/missing script metadata for editor repair."""

    component_type = "missing_script"

    def __init__(self, raw: dict[str, Any]) -> None:
        super().__init__(enabled=bool(raw.get("enabled", True)))
        self.raw = dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


__all__ = ["ScriptComponent", "UnresolvedScriptComponent"]
