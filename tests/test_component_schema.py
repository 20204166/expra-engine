import math
from dataclasses import dataclass

import pytest

from expra_engine.core.component import Component, TransformComponent, register_component_type
from expra_engine.core.component_schema import (
    ComponentTypeSpec,
    PropertyDescriptor,
    component_type_spec,
    register_component_spec,
)
from expra_engine.runtime.visual_components import SpriteComponent


def test_property_descriptor_converts_supported_editor_values() -> None:
    assert PropertyDescriptor("speed", "Speed", float, 1.0).convert("2.5") == 2.5
    assert PropertyDescriptor("count", "Count", int, 1).convert("3") == 3
    assert PropertyDescriptor("enabled", "Enabled", bool, True).convert("false") is False
    assert PropertyDescriptor("mode", "Mode", str, "idle", enum_values=("idle", "run")).convert(
        "run"
    ) == "run"
    assert PropertyDescriptor("color", "Color", tuple, (1.0, 1.0, 1.0)).convert(
        "0.1, 0.2, 0.3"
    ) == (0.1, 0.2, 0.3)


def test_property_descriptor_rejects_invalid_input_and_non_finite_numbers() -> None:
    descriptor = PropertyDescriptor("speed", "Speed", float, 1.0, minimum=0.0, maximum=10.0)
    assert descriptor.convert("not-a-number", original=4.0) == 4.0
    assert descriptor.convert("-1", original=4.0) == 4.0
    assert descriptor.convert(str(math.inf), original=4.0) == 4.0


def test_sprite_region_descriptor_rejects_fractional_pixel_values() -> None:
    spec = component_type_spec("sprite")
    assert spec.cls is SpriteComponent
    region = next(field for field in spec.fields if field.name == "region")

    assert region.convert("1.5, 2, 3, 4", original=(1, 2, 3, 4)) == (1, 2, 3, 4)


def test_read_only_descriptor_returns_original_value() -> None:
    descriptor = PropertyDescriptor("id", "ID", str, "a", editable=False)
    assert descriptor.convert("b", original="a") == "a"


def test_component_spec_is_immutable_and_records_required_types() -> None:
    spec = ComponentTypeSpec(
        "example",
        Component,
        (PropertyDescriptor("value", "Value", int, 0),),
        (TransformComponent,),
    )
    with pytest.raises(AttributeError):
        spec.name = "changed"
    assert spec.required_types == (TransformComponent,)


def test_transform_metadata_is_registered_and_unknown_types_are_clear() -> None:
    spec = component_type_spec("transform")
    assert spec.cls is TransformComponent
    assert tuple(field.name for field in spec.fields) == (
        "x",
        "y",
        "rotation",
        "scale_x",
        "scale_y",
    )
    with pytest.raises(KeyError, match="Unknown component type"):
        component_type_spec("missing")


def test_registered_custom_component_keeps_serialization_registry_behavior() -> None:
    @dataclass
    class TestComponent(Component):
        component_type: str = "test_schema_component"
        amount: float = 1.0

        def to_dict(self):
            return {"type": self.component_type, "enabled": self.enabled, "amount": self.amount}

        @classmethod
        def from_dict(cls, data):
            return cls(enabled=bool(data.get("enabled", True)), amount=float(data.get("amount", 1)))

    register_component_type(TestComponent.component_type, TestComponent)
    register_component_spec(
        ComponentTypeSpec(
            TestComponent.component_type,
            TestComponent,
            (PropertyDescriptor("amount", "Amount", float, 1.0),),
            (TransformComponent,),
        )
    )
    assert component_type_spec(TestComponent.component_type).cls is TestComponent
