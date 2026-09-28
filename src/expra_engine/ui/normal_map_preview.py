"""Non-mutating normal-map preview surfaces and their small Tk presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from expra_engine.runtime.pygame_normal_mapping import decode_normal_pixels, shade_normal_mapped_rgb
from expra_engine.runtime.rendering import Color, LightDescriptor, NormalMapDescriptor

__all__ = ("NormalMapPreview", "build_normal_map_preview", "show_normal_map_preview")


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


def show_normal_map_preview(parent: Any, preview: NormalMapPreview, metadata: str) -> Any:
    """Present the four preview views in a modeless editor-owned window."""
    import tkinter as tk
    from tkinter import ttk

    from PIL import Image, ImageTk

    window = tk.Toplevel(parent)
    window.title("Normal Map Preview")
    window.transient(parent)
    ttk.Label(window, text=metadata, justify="left").pack(fill="x", padx=12, pady=8)
    notebook = ttk.Notebook(window)
    notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    images: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    lit_state = {
        "x": preview.views["Lit"].get_width() * 0.5,
        "y": preview.views["Lit"].get_height() * 0.5,
    }

    def photo(surface: Any) -> Any:
        import pygame

        width, height = surface.get_size()
        image = Image.frombytes("RGBA", (width, height), pygame.image.tostring(surface, "RGBA"))
        image.thumbnail((384, 384), Image.Resampling.NEAREST)
        return ImageTk.PhotoImage(image, master=window)

    for name, surface in preview.views.items():
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=name)
        images[name] = photo(surface)
        labels[name] = ttk.Label(tab, image=images[name])
        labels[name].pack(padx=8, pady=8)
        if name == "Lit":
            controls = ttk.Frame(tab)
            controls.pack(fill="x", padx=8, pady=(0, 8))
            ttk.Label(controls, text="Light height").pack(side="left")
            height = tk.DoubleVar(value=max(1.0, surface.get_width() * 0.5))

            def update_lit(_value: object = None, height_var: Any = height) -> None:
                lit_surface = preview.render_lit(
                    float(lit_state["x"]),
                    float(lit_state["y"]),
                    height_var.get(),
                )
                images["Lit"] = photo(lit_surface)
                labels["Lit"].configure(image=images["Lit"])

            ttk.Scale(
                controls,
                from_=0.0,
                to=max(surface.get_size()),
                variable=height,
                command=update_lit,
            ).pack(side="left", fill="x", expand=True, padx=(8, 0))

            def move_light(event: Any, lit_size: tuple[int, int] = surface.get_size()) -> None:
                image = images["Lit"]
                width, image_height = lit_size
                lit_state["x"] = event.x / max(1, image.width()) * width - width * 0.5
                lit_state["y"] = image_height * 0.5 - event.y / max(1, image.height()) * image_height
                update_lit()

            labels[name].bind("<Button-1>", move_light)
            labels[name].bind("<B1-Motion>", move_light)
        elif name == "Orientation test":
            controls = ttk.Frame(tab)
            controls.pack(pady=(0, 8))
            for direction, direction_surface in preview.orientation_views.items():
                def select(value: str = direction, value_surface: Any = direction_surface) -> None:
                    images["Orientation test"] = photo(value_surface)
                    labels["Orientation test"].configure(image=images["Orientation test"])

                ttk.Button(controls, text=direction, command=select).pack(side="left", padx=2)
    cast(Any, window)._normal_map_images = images
    return window
