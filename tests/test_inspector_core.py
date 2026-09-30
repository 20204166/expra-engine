"""Toolkit-independent inspector value conversion and formatting."""

from expra_engine.core.component_schema import PropertyDescriptor
from expra_engine.editor.inspector_core import InspectorCore


def test_component_value_conversion_uses_descriptor_rejection_policy() -> None:
    descriptor = PropertyDescriptor("x", "X", float, 0.0, minimum=-10.0, maximum=10.0)

    assert InspectorCore.convert_component_value(descriptor, "2.5", 1.0) == 2.5
    assert InspectorCore.convert_component_value(descriptor, "bad", 1.0) == 1.0


def test_component_value_formatting_handles_sequences_and_none() -> None:
    assert InspectorCore.format_component_value((1.5, -2.0)) == "1.5, -2.0"
    assert InspectorCore.format_component_value(None) == ""
