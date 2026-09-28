"""Canonical wording for component diagnostics."""

from __future__ import annotations


def unknown_component_type(component_type: object) -> str:
    """Describe a component type that is not registered."""
    return f"Unknown component type: {component_type!r}"
