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
    component_type_spec,
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
    _register_builtin_components()
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
    try:
        component_type_spec(name)
    except KeyError:
        register_component_spec(ComponentTypeSpec(name, cls))


def registered_component_types() -> tuple[tuple[str, type[Component]], ...]:
    """Return registered component types in registration order for editor tooling."""
    _register_builtin_components()
    return tuple(_COMPONENT_REGISTRY.items())


def _register_component(
    component_type: str,
    cls: type[Component],
    fields: tuple[PropertyDescriptor, ...] = (),
    required_types: tuple[type, ...] = (),
) -> None:
    """Record ``cls`` in both the serialization registry and the editor spec registry."""
    _COMPONENT_REGISTRY[component_type] = cls
    register_component_spec(ComponentTypeSpec(component_type, cls, fields, required_types))


def _register_builtin_components() -> None:
    """Ensure every built-in component category is registered (each is idempotent)."""
    _register_visual_components()
    _register_physics_components()
    _register_audio_components()
    _register_screen_components()
    _register_composition_components()


def _register_visual_components() -> None:
    if "primitive" in _COMPONENT_REGISTRY:
        return
    from expra_engine.runtime.animated_sprite_2d import AnimatedSprite2DComponent, SpriteFrames2D
    from expra_engine.runtime.canvas_effects import CanvasModulateComponent
    from expra_engine.runtime.visual_components import (
        PrimitiveComponent,
        SpriteComponent,
        TextComponent,
    )

    registrations: tuple[tuple[str, type[Component], tuple[PropertyDescriptor, ...]], ...] = (
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
                PropertyDescriptor(
                    "region",
                    "Region",
                    tuple,
                    None,
                    tuple_length=4,
                    tuple_minimum=(0.0, 0.0, 1.0, 1.0),
                    tuple_integer=True,
                ),
                PropertyDescriptor("centered", "Centered", bool, True),
                PropertyDescriptor("offset", "Offset", tuple, (0.0, 0.0), tuple_length=2),
                PropertyDescriptor("flip_h", "Flip Horizontal", bool, False),
                PropertyDescriptor("flip_v", "Flip Vertical", bool, False),
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
                PropertyDescriptor(
                    "align", "Align", str, "left", enum_values=("left", "center", "right")
                ),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor("visible", "Visible", bool, True),
            ),
        ),
        (
            AnimatedSprite2DComponent.component_type,
            AnimatedSprite2DComponent,
            (
                PropertyDescriptor("frames", "Frames", SpriteFrames2D, SpriteFrames2D()),
                PropertyDescriptor("animation", "Animation", str, "default"),
                PropertyDescriptor("autoplay", "Autoplay", str, ""),
                PropertyDescriptor("frame", "Frame", int, 0, minimum=0),
                PropertyDescriptor(
                    "frame_progress", "Frame Progress", float, 0.0, minimum=0.0, maximum=1.0
                ),
                PropertyDescriptor("speed_scale", "Speed Scale", float, 1.0),
                PropertyDescriptor("centered", "Centered", bool, True),
                PropertyDescriptor("offset", "Offset", tuple, (0.0, 0.0), tuple_length=2),
                PropertyDescriptor("flip_h", "Flip Horizontal", bool, False),
                PropertyDescriptor("flip_v", "Flip Vertical", bool, False),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor("visible", "Visible", bool, True),
            ),
        ),
        (
            CanvasModulateComponent.component_type,
            CanvasModulateComponent,
            (
                PropertyDescriptor("color", "Color", tuple, (1.0, 1.0, 1.0, 1.0)),
                PropertyDescriptor("enabled", "Enabled", bool, True),
            ),
        ),
    )
    for component_type, component_cls, fields in registrations:
        _register_component(component_type, component_cls, fields)


def _register_screen_components() -> None:
    if "back_buffer_copy" in _COMPONENT_REGISTRY:
        return
    from expra_engine.runtime.screen_texture import (
        BackBufferCopyComponent,
        ScreenTextureComponent,
    )

    registrations: tuple[tuple[str, type[Component], tuple[PropertyDescriptor, ...]], ...] = (
        (
            BackBufferCopyComponent.component_type,
            BackBufferCopyComponent,
            (
                PropertyDescriptor(
                    "copy_mode",
                    "Copy Mode",
                    str,
                    "rect",
                    enum_values=("disabled", "rect", "viewport"),
                ),
                PropertyDescriptor(
                    "rect",
                    "Rect",
                    tuple,
                    (-100.0, -100.0, 200.0, 200.0),
                    tuple_length=4,
                ),
                PropertyDescriptor("capture_id", "Capture ID", str, "screen"),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor(
                    "phase",
                    "Phase",
                    str,
                    "opaque",
                    enum_values=("opaque", "transparent", "overlay"),
                ),
                PropertyDescriptor("enabled", "Enabled", bool, True),
            ),
        ),
        (
            ScreenTextureComponent.component_type,
            ScreenTextureComponent,
            (
                PropertyDescriptor("capture_id", "Capture ID", str, "screen"),
                PropertyDescriptor(
                    "uv_rect",
                    "UV Rect",
                    tuple,
                    (0.0, 0.0, 1.0, 1.0),
                    tuple_length=4,
                ),
                PropertyDescriptor("width", "Width", float, 1.0, minimum=0.0),
                PropertyDescriptor("height", "Height", float, 1.0, minimum=0.0),
                PropertyDescriptor(
                    "filter",
                    "Filter",
                    str,
                    "linear",
                    enum_values=("nearest", "linear", "nearest_mipmap", "linear_mipmap"),
                ),
                PropertyDescriptor("lod", "LOD", float, 0.0, minimum=0.0),
                PropertyDescriptor("tint", "Tint", tuple, (1.0, 1.0, 1.0, 1.0)),
                PropertyDescriptor("opacity", "Opacity", float, 1.0, minimum=0.0, maximum=1.0),
                PropertyDescriptor("layer", "Layer", int, 0),
                PropertyDescriptor(
                    "phase",
                    "Phase",
                    str,
                    "transparent",
                    enum_values=("opaque", "transparent", "overlay"),
                ),
                PropertyDescriptor("visible", "Visible", bool, True),
                PropertyDescriptor("enabled", "Enabled", bool, True),
            ),
        ),
    )
    for component_type, component_cls, fields in registrations:
        _register_component(component_type, component_cls, fields)


def _register_physics_components() -> None:
    if "collider" not in _COMPONENT_REGISTRY:
        from expra_engine.runtime.collider import ColliderComponent

        collider_fields: tuple[PropertyDescriptor, ...] = (
            PropertyDescriptor(
                "shape", "Shape", str, "rectangle", enum_values=("rectangle", "circle")
            ),
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
        _register_component("collider", ColliderComponent, collider_fields)

    if "area" not in _COMPONENT_REGISTRY:
        from expra_engine.runtime.area import AreaComponent, SpaceOverride
        from expra_engine.runtime.collider import ColliderComponent

        modes = tuple(mode.value for mode in SpaceOverride)
        area_fields: tuple[PropertyDescriptor, ...] = (
            PropertyDescriptor("priority", "Priority", int, 0),
            PropertyDescriptor("gravity_mode", "Gravity Mode", str, "disabled", enum_values=modes),
            PropertyDescriptor("gravity", "Gravity", float, 0.0),
            PropertyDescriptor("gravity_direction", "Gravity Direction", tuple, (0.0, -1.0)),
            PropertyDescriptor("gravity_point", "Point Gravity", bool, False),
            PropertyDescriptor("gravity_point_center", "Point Center", tuple, (0.0, 0.0)),
            PropertyDescriptor(
                "gravity_point_unit_distance", "Point Unit Distance", float, 0.0, minimum=0.0
            ),
            PropertyDescriptor(
                "linear_damp_mode", "Linear Damp Mode", str, "disabled", enum_values=modes
            ),
            PropertyDescriptor("linear_damp", "Linear Damp", float, 0.0, minimum=0.0),
            PropertyDescriptor(
                "angular_damp_mode", "Angular Damp Mode", str, "disabled", enum_values=modes
            ),
            PropertyDescriptor("angular_damp", "Angular Damp", float, 0.0, minimum=0.0),
            PropertyDescriptor("enabled", "Enabled", bool, True),
        )
        _register_component("area", AreaComponent, area_fields, (ColliderComponent,))


def _register_audio_components() -> None:
    if "audio_listener_2d" in _COMPONENT_REGISTRY:
        return
    from expra_engine.runtime.audio_2d import (
        AudioListener2DComponent,
        AudioStreamPlayer2DComponent,
        PlaybackType2D,
    )

    _register_component(
        "audio_listener_2d",
        AudioListener2DComponent,
        (
            PropertyDescriptor("current", "Current Listener", bool, False),
            PropertyDescriptor("enabled", "Enabled", bool, True),
        ),
    )
    _register_component(
        "audio_stream_player_2d",
        AudioStreamPlayer2DComponent,
        (
            PropertyDescriptor("asset_id", "Audio Asset", str, ""),
            PropertyDescriptor("volume_db", "Volume (dB)", float, 0.0),
            PropertyDescriptor("pitch_scale", "Pitch Scale", float, 1.0, minimum=0.000001),
            PropertyDescriptor("autoplay", "Autoplay", bool, False),
            PropertyDescriptor("stream_paused", "Paused", bool, False),
            PropertyDescriptor("max_distance", "Max Distance", float, 2000.0, minimum=0.000001),
            PropertyDescriptor("attenuation", "Attenuation", float, 1.0, minimum=0.0),
            PropertyDescriptor("max_polyphony", "Max Polyphony", int, 1, minimum=1),
            PropertyDescriptor("panning_strength", "Panning Strength", float, 1.0, minimum=0.0),
            PropertyDescriptor(
                "bus",
                "Bus",
                str,
                "sfx",
                enum_values=("master", "music", "sfx", "ambience", "dialogue", "ui"),
            ),
            PropertyDescriptor("area_mask", "Area Mask", int, 0, minimum=0, maximum=0xFFFFFFFF),
            PropertyDescriptor(
                "playback_type",
                "Playback Type",
                str,
                PlaybackType2D.DEFAULT.value,
                enum_values=tuple(mode.value for mode in PlaybackType2D),
            ),
            PropertyDescriptor("enabled", "Enabled", bool, True),
        ),
    )


def _register_composition_components() -> None:
    if "scene_instance" in _COMPONENT_REGISTRY:
        return
    from expra_engine.core.scene.scene_instance import SceneInstanceComponent

    _register_component(
        "scene_instance",
        SceneInstanceComponent,
        (
            PropertyDescriptor("source_path", "Source Scene", str, ""),
            PropertyDescriptor("enabled", "Enabled", bool, True),
        ),
    )
