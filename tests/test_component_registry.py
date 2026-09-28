"""The component class registry and editor spec registry share one owner."""

from __future__ import annotations

from dataclasses import dataclass

from expra_engine.core.component import (
    Component,
    component_from_dict,
    register_component_type,
    registered_component_types,
)
from expra_engine.core.component_schema import registered_component_specs


def test_component_types_derive_from_editor_specs() -> None:
    types = dict(registered_component_types())
    specs = {spec.name: spec.cls for spec in registered_component_specs()}
    assert types == specs


def test_deserializing_script_component_does_not_leak_into_registry() -> None:
    component_from_dict({"type": "script", "script_id": "s", "behaviour_class": "Foo"})

    names = [name for name, _cls in registered_component_types()]
    assert "script" not in names


def test_custom_registration_appears_in_both_views() -> None:
    @dataclass
    class Tag(Component):
        component_type: str = "registry_tag"
        value: str = ""

        def to_dict(self):
            return {"type": self.component_type, "value": self.value}

        @classmethod
        def from_dict(cls, data):
            return cls(value=str(data.get("value", "")))

    register_component_type("registry_tag", Tag)
    restored = component_from_dict({"type": "registry_tag", "value": "x"})
    assert isinstance(restored, Tag)
    assert dict(registered_component_types())["registry_tag"] is Tag
