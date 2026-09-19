"""Renderer-neutral design language primitives.

The editor adapts these semantic values to Tk styles. Future game UI backends
can adapt the same concepts to a renderer without importing editor dependencies.
"""

from expra_engine.design.tokens import (
    CONTROL_METRICS,
    PANEL_HIERARCHY,
    RESPONSIVE_RULES,
    SEMANTIC_COLORS,
    SPACING_SCALE,
    STATE_STYLES,
    TYPOGRAPHY_SCALE,
)

__all__ = (
    "CONTROL_METRICS",
    "PANEL_HIERARCHY",
    "RESPONSIVE_RULES",
    "SEMANTIC_COLORS",
    "SPACING_SCALE",
    "STATE_STYLES",
    "TYPOGRAPHY_SCALE",
)
