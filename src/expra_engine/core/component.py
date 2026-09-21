"""Component model — data attached to an Entity.

Components are plain data containers. The Inspector reads and writes them
through the action boundary; they never mutate themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from expra_engine.core.component_schema import (
    ComponentTypeSpec,
    PropertyDescriptor,
    register_component_spec,
)


class Component:
    """Base class for all engine components.

    Subclasses should be dataclasses. ``component_type`` identifies the
    component for serialization. ``enabled`` controls whether the runtime
    processes this component.
    """

    component_type: str = "component"

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.component_type, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Component:
        return cls(enabled=data.get("enabled", True))


@dataclass
class TransformComponent(Component):
    """2D transform: position, rotation, and scale.

    Kept simple and 2D; no matrices or quaternions until a 3D renderer
    needs them.
    """

    component_type: str = field(default="transform", init=False, repr=False)

    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0

    def __init__(
        self,
        *,
        x: float = 0.0,
        y: float = 0.0,
        rotation: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        self.x = x
        self.y = y
        self.rotation = rotation
        self.scale_x = scale_x
        self.scale_y = scale_y

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransformComponent:
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            rotation=float(data.get("rotation", 0.0)),
            scale_x=float(data.get("scale_x", 1.0)),
            scale_y=float(data.get("scale_y", 1.0)),
            enabled=bool(data.get("enabled", True)),
        )


_COMPONENT_REGISTRY: dict[str, type[Component]] = {
    "transform": TransformComponent,
}

register_component_spec(
    ComponentTypeSpec(
        "transform",
        TransformComponent,
        tuple(
            PropertyDescriptor(name, label, float, default)
            for name, label, default in (
                ("x", "Position X", 0.0),
                ("y", "Position Y", 0.0),
                ("rotation", "Rotation", 0.0),
                ("scale_x", "Scale X", 1.0),
                ("scale_y", "Scale Y", 1.0),
            )
        ),
    )
)


def component_from_dict(data: dict[str, Any]) -> Component:
    """Deserialize a component from its dict representation."""
    _register_visual_components()
    _register_physics_components()
    component_type = data.get("type", "")
    if component_type == "script":
        from expra_engine.runtime.script_component import (
            ScriptComponent,
            UnresolvedScriptComponent,
        )

        _COMPONENT_REGISTRY[component_type] = ScriptComponent
        try:
            return ScriptComponent.from_dict(data)
        except (TypeError, ValueError, KeyError):
            return UnresolvedScriptComponent(data)
    cls = _COMPONENT_REGISTRY.get(component_type)
    if cls is None:
        raise ValueError(f"Unknown component type: {component_type!r}")
    return cls.from_dict(data)


def register_component_type(name: str, cls: type[Component]) -> None:
    """Register a custom component type for deserialization."""
    _COMPONENT_REGISTRY[name] = cls
    from expra_engine.core.component_schema import component_type_spec

    try:
        component_type_spec(name)
    except KeyError:
        register_component_spec(ComponentTypeSpec(name, cls))


def registered_component_types() -> tuple[tuple[str, type[Component]], ...]:
    """Return registered component types in registration order for editor tooling."""
    _register_visual_components()
    _register_physics_components()
    return tuple(_COMPONENT_REGISTRY.items())


def _register_visual_components() -> None:
    if "primitive" in _COMPONENT_REGISTRY:
        return
    from expra_engine.runtime.visual_components import (
        PrimitiveComponent,
        SpriteComponent,
        TextComponent,
    )

    registrations = (
        (
            PrimitiveComponent.component_type,
            PrimitiveComponent,
            (
                PropertyDescriptor("kind", "Kind", str, "rectangle"),
                PropertyDescriptor("width", "Width", float, 1.0),
                PropertyDescriptor("height", "Height", float, 1.0),
                PropertyDescriptor("radius", "Radius", float, None),
                PropertyDescriptor("fill", "Fill", tuple, (1.0, 1.0, 1.0, 1.0)),
                PropertyDescriptor("outline", "Outline", tuple, None),
                PropertyDescriptor("outline_width", "Outline Width", float, 0.0),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor("visible", "Visible", bool, True),
            ),
        ),
        (
            SpriteComponent.component_type,
            SpriteComponent,
            (
                PropertyDescriptor("asset", "Asset", str, ""),
                PropertyDescriptor("tint", "Tint", tuple, (1.0, 1.0, 1.0, 1.0)),
                PropertyDescriptor("width", "Width", float, 1.0),
                PropertyDescriptor("height", "Height", float, 1.0),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor("visible", "Visible", bool, True),
            ),
        ),
        (
            TextComponent.component_type,
            TextComponent,
            (
                PropertyDescriptor("text", "Text", str, ""),
                PropertyDescriptor("font", "Font", str, "default"),
                PropertyDescriptor("size", "Size", float, 16.0),
                PropertyDescriptor("color", "Color", tuple, (1.0, 1.0, 1.0, 1.0)),
                PropertyDescriptor("max_width", "Max Width", float, None),
                PropertyDescriptor("align", "Align", str, "left", enum_values=("left", "center", "right")),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor("visible", "Visible", bool, True),
            ),
        ),
    )
    for component_type, component_cls, fields in registrations:
        _COMPONENT_REGISTRY[component_type] = component_cls
        register_component_spec(ComponentTypeSpec(component_type, component_cls, fields))


def _register_physics_components() -> None:
    if "collider" in _COMPONENT_REGISTRY:
        return
    from expra_engine.runtime.collider import ColliderComponent

    fields = (
        PropertyDescriptor("shape", "Shape", str, "rectangle", enum_values=("rectangle", "circle")),
        PropertyDescriptor("width", "Width", float, 1.0, minimum=0.0),
        PropertyDescriptor("height", "Height", float, 1.0, minimum=0.0),
        PropertyDescriptor("radius", "Radius", float, None, minimum=0.0),
        PropertyDescriptor("offset", "Offset", tuple, (0.0, 0.0)),
        PropertyDescriptor("solid", "Solid", bool, True),
        PropertyDescriptor("trigger", "Trigger", bool, False),
        PropertyDescriptor("enabled", "Enabled", bool, True),
        PropertyDescriptor("layer", "Layer", int, 1, minimum=0),
        PropertyDescriptor("mask", "Mask", int, 0xFFFFFFFF, minimum=0),
    )
    _COMPONENT_REGISTRY["collider"] = ColliderComponent
    register_component_spec(ComponentTypeSpec("collider", ColliderComponent, fields))
