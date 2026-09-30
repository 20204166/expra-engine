"""Renderer-neutral canvas-wide visual effects.

This is the dependency-stripped capability retained from Godot's
``CanvasModulate`` after auditing Expra's existing rendering architecture.

``CanvasGroup`` is intentionally not reproduced here. Its meaningful behavior
depends on off-screen subtree rendering/compositing, render-target margins, and
mipmapped intermediate textures. Expra does not currently expose that render
pass contract, so carrying those settings would create inert configuration.

The component below is plain serialized scene data. Runtime selection stays
deterministic and renderer-neutral; the canonical render extractor/renderer is
responsible for consuming the resolved modulation.

Godot Engine source is MIT licensed:
Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md).
Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from expra_engine.core.component import Component
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import Color

__all__ = (
    "CanvasModulateComponent",
    "CanvasModulation",
    "modulate_color",
    "resolve_canvas_modulation",
)


_WHITE = Color(1.0, 1.0, 1.0, 1.0)


def modulate_color(color: Color, modulation: Color) -> Color:
    """Multiply two RGBA colours channel-by-channel."""

    if not isinstance(color, Color) or not isinstance(modulation, Color):
        raise TypeError("color and modulation must be rendering.Color values")
    return Color(
        color.red * modulation.red,
        color.green * modulation.green,
        color.blue * modulation.blue,
        color.alpha * modulation.alpha,
    )


class CanvasModulateComponent(Component):
    """Scene-wide colour modulation configuration.

    Exactly one enabled modulation is consumed for a scene. When more than one
    exists, ``resolve_canvas_modulation`` deterministically selects the first
    eligible entity in scene insertion order and reports the duplicate count.

    ``enabled`` participates in normal Expra component lifecycle semantics.
    There is no separate visibility flag because an owning disabled entity is
    already excluded by the resolver.
    """

    component_type = "canvas_modulate"

    def __init__(
        self,
        color: Color | tuple[float, ...] | list[float] = _WHITE,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.color = Color.from_value(color)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "color": self.color.to_list(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanvasModulateComponent:
        return cls(
            data.get("color", (1.0, 1.0, 1.0, 1.0)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class CanvasModulation:
    """Resolved scene-wide modulation consumed by rendering."""

    color: Color = _WHITE
    source_entity_id: str | None = None
    duplicate_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.color, Color):
            raise TypeError("color must be a rendering.Color")
        if self.duplicate_count < 0:
            raise ValueError("duplicate_count must be non-negative")

    @property
    def active(self) -> bool:
        return self.source_entity_id is not None


def resolve_canvas_modulation(
    scene: Scene,
    *,
    entity_ids: Iterable[str] | None = None,
) -> CanvasModulation:
    """Resolve the active modulation without mutating scene or render state.

    Selection follows scene insertion order so multiple components never create
    backend-dependent or hash-order-dependent results. Disabled entities and
    disabled components are ignored.
    """

    if not isinstance(scene, Scene):
        raise TypeError("scene must be a Scene")

    eligible_ids: frozenset[str] | None = None
    if entity_ids is not None:
        if isinstance(entity_ids, (str, bytes)):
            raise TypeError("entity_ids must be an iterable of Entity ID strings")
        try:
            eligible_ids = frozenset(entity_ids)
        except TypeError as exc:
            raise TypeError("entity_ids must be an iterable of Entity ID strings") from exc
        if any(not isinstance(entity_id, str) for entity_id in eligible_ids):
            raise TypeError("entity_ids must contain only strings")

    selected: tuple[str, CanvasModulateComponent] | None = None
    duplicates = 0

    for entity in scene.entities:
        if eligible_ids is not None and entity.entity_id not in eligible_ids:
            continue
        if not entity.enabled:
            continue
        component = entity.get_component(CanvasModulateComponent)
        if component is None or not component.enabled:
            continue
        if selected is None:
            selected = (entity.entity_id, component)
        else:
            duplicates += 1

    if selected is None:
        return CanvasModulation()

    entity_id, component = selected
    return CanvasModulation(
        color=component.color,
        source_entity_id=entity_id,
        duplicate_count=duplicates,
    )
