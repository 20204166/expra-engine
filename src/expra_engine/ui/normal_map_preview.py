"""Non-mutating normal-map preview surfaces (toolkit-independent preview model)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from expra_engine.runtime.pygame_normal_mapping import decode_normal_pixels, shade_normal_mapped_rgb
from expra_engine.runtime.rendering import Color, LightDescriptor, NormalMapDescriptor

__all__ = ("NormalMapPreview", "build_normal_map_preview")


@dataclass(frozen=True, slots=True)
class NormalMapPreview:
    views: dict[str, Any]
    orientation_views: dict[str, Any]
    render_lit: Callable[[float, float, float], Any]


def build_normal_map_preview(
    pygame_module: Any,
    albedo_surface: Any,
    normal_surface: Any,
    descriptor: NormalMapDescriptor,
) -> NormalMapPreview:
    """Build raw, decoded, lit, and cardinal views without mutating source Surfaces."""
    import numpy as np

    source_size = normal_surface.get_size()
    if source_size[0] <= 0 or source_size[1] <= 0:
        raise ValueError("normal texture dimensions must be positive")
    scale = min(1.0, 384.0 / max(source_size))
    size = (
        max(1, round(source_size[0] * scale)),
        max(1, round(source_size[1] * scale)),
    )
    if size != source_size:
        normal_surface = pygame_module.transform.smoothscale(normal_surface, size)
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError("normal texture dimensions must be positive")
    raw = normal_surface.copy()
    normal_pixels = pygame_module.surfarray.array3d(normal_surface)
    normals = decode_normal_pixels(
        normal_pixels,
        descriptor.encoding,
        descriptor.y_convention,
        descriptor.strength,
    )
    decoded_rgb = np.rint(np.clip(normals * 0.5 + 0.5, 0.0, 1.0) * 255.0).astype(np.uint8)
    decoded = pygame_module.Surface(size, pygame_module.SRCALPHA, 32)
    pygame_module.surfarray.blit_array(decoded, decoded_rgb)

    albedo = pygame_module.transform.smoothscale(albedo_surface, size)
    world_x = np.broadcast_to(
        np.arange(size[0], dtype=np.float32)[:, None] - np.float32(size[0] / 2), size
    )
    world_y = np.broadcast_to(
        np.float32(size[1] / 2) - np.arange(size[1], dtype=np.float32)[None, :], size
    )
    attenuation = np.ones(size, dtype=np.float32)
    distance = float(max(size))

    def shaded(light: LightDescriptor) -> Any:
        source_rgb = pygame_module.surfarray.array3d(albedo)
        rgb = shade_normal_mapped_rgb(
            source_rgb,
            normals,
            world_x,
            world_y,
            ((light, attenuation),),
            ambient=Color(0.12, 0.12, 0.12),
            diffuse=1.0,
        )
        result = albedo.copy()
        pygame_module.surfarray.blit_array(result, rgb)
        return result

    def render_lit(light_x: float, light_y: float, height: float) -> Any:
        return shaded(
            LightDescriptor(
                "preview",
                "point",
                (light_x, light_y, 0.0),
                Color(1, 1, 1),
                1.0,
                distance * 2,
                2.0,
                height=height,
            )
        )

    orientation_lights = {
        "Left": (-distance, 0.0, 0.0),
        "Right": (distance, 0.0, 0.0),
        "Up": (0.0, distance, 0.0),
        "Down": (0.0, -distance, 0.0),
    }
    orientation_views = {
        name: shaded(
            LightDescriptor(name.casefold(), "point", position, Color(1, 1, 1), 1.0, distance * 2, 2.0, height=0.0)
        )
        for name, position in orientation_lights.items()
    }
    lit = render_lit(distance * 0.5, distance * 0.5, max(1.0, distance * 0.5))
    return NormalMapPreview(
        {
            "Raw": raw,
            "Decoded normal": decoded,
            "Lit": lit,
            "Orientation test": orientation_views["Right"],
        },
        orientation_views,
        render_lit,
    )
