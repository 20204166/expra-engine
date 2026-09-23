"""Optional Pygame-to-Tk pixel bridge used by the editor viewport."""

from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable
from io import BytesIO
from typing import Any, cast

from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, RenderFrame, Viewport

__all__ = (
    "EditorPixelRenderer",
    "encode_pygame_surface",
    "frame_textures_available",
    "render_editor_frame_to_image",
    "render_editor_frame_to_tk_image",
)


def render_editor_frame_to_image(
    frame: RenderFrame,
    context: RenderContext,
    *,
    surface_factory: Callable[[tuple[int, int]], Any],
    renderer_factory: Callable[[Any], Any],
    encode_surface: Callable[[Any], bytes],
    image_factory: Callable[[bytes], Any],
) -> Any | None:
    """Render one canonical frame and bridge its pixels into Tk safely."""
    try:
        surface = surface_factory((context.viewport.width, context.viewport.height))
        renderer = renderer_factory(surface)
        renderer.start(context)
        renderer.render(frame)
        if getattr(renderer, "draw_failed", False):
            return None
        return image_factory(encode_surface(surface))
    except Exception:
        return None


def encode_pygame_surface(pygame_module: Any, surface: Any) -> bytes:
    """Encode an offscreen surface in a format Tk can decode."""
    stream = BytesIO()
    pygame_module.image.save(surface, stream, "PNG")
    return stream.getvalue()


def frame_textures_available(
    frame: RenderFrame,
    context: RenderContext,
    resource_provider: Callable[[str], Any | None],
) -> bool:
    """Return whether every visible texture can participate in pixel rendering."""
    try:
        items = frame.visible_items(context)
        for item in items:
            texture_id = item.material.texture_id
            if texture_id is None and item.nine_slice is not None:
                texture_id = item.nine_slice.texture_id
            if texture_id is None and item.text is None and item.nine_slice is None:
                if item.primitive.kind not in {"rectangle", "rect", "circle", "point"}:
                    return False
                if item.primitive.kind in {"rectangle", "rect"} and (
                    item.world_transform.rotation or context.camera.rotation
                ):
                    return False
                if item.primitive.kind in {"circle", "point"} and (
                    item.material.outline is not None and item.material.outline_width
                ):
                    return False
            if texture_id is None:
                continue
            texture = resource_provider(texture_id)
            if texture is None:
                return False
            region = item.material.source_region
            if region is None:
                continue
            get_size = getattr(texture, "get_size", None)
            if not callable(get_size):
                continue
            width, height = cast(tuple[int, int], get_size())
            if (
                region.x < 0
                or region.y < 0
                or region.x + region.width > width
                or region.y + region.height > height
            ):
                return False
    except Exception:
        return False
    return True


def render_editor_frame_to_tk_image(
    frame: RenderFrame,
    context: RenderContext,
    *,
    width: int,
    height: int,
    resource_service: Any | None,
    resource_provider: PygameResourceProvider | None,
    pygame_module: Any,
    image_master: Any,
) -> Any | None:
    """Render a complete editor frame, or return ``None`` for Tk fallback."""
    if resource_service is None or resource_provider is None:
        return None
    if not frame_textures_available(frame, context, resource_provider):
        return None
    try:
        font_init = getattr(getattr(pygame_module, "font", None), "init", None)
        if callable(font_init):
            font_init()
        image_init = getattr(getattr(pygame_module, "image", None), "init", None)
        if callable(image_init):
            image_init()
        flags = getattr(pygame_module, "SRCALPHA", 0)

        def surface_factory(size: tuple[int, int]) -> Any:
            return pygame_module.Surface(size, flags=flags)

        def renderer_factory(surface: Any) -> PygameRenderer:
            return PygameRenderer(
                pygame_module,
                surface,
                screen_size=(width, height),
                arena_bounds=(0, 0, width, height),
                resource_provider=resource_provider,
                clear_color=None,
            )

        return render_editor_frame_to_image(
            frame,
            context,
            surface_factory=surface_factory,
            renderer_factory=renderer_factory,
            encode_surface=lambda surface: encode_pygame_surface(pygame_module, surface),
            image_factory=lambda data: tk.PhotoImage(
                master=image_master,
                data=base64.b64encode(data).decode("ascii"),
            ),
        )
    except Exception:
        return None


def editor_render_context(editor_camera: Any, width: int, height: int) -> RenderContext:
    camera_width = editor_camera._camera.width
    camera_height = camera_width * height / width
    camera = OrthographicCamera(width=camera_width, height=camera_height)
    camera.position = editor_camera.position
    camera.rotation = editor_camera._camera.rotation
    return RenderContext(Viewport(0, 0, width, height), camera)


class EditorPixelRenderer:
    """Own optional Pygame resources and produce a complete Tk image."""

    def __init__(self, resource_service: Any | None = None) -> None:
        self._resource_service = resource_service
        self._provider: PygameResourceProvider | None = None
        self._provider_resources: Any | None = None

    @property
    def resource_service(self) -> Any | None:
        return self._resource_service

    def set_resource_service(self, resource_service: Any | None) -> None:
        if resource_service is self._resource_service:
            return
        self._resource_service = resource_service
        self._provider = None
        self._provider_resources = None

    def render(
        self,
        frame: RenderFrame,
        editor_camera: Any,
        width: int,
        height: int,
        image_master: Any,
    ) -> Any | None:
        if self._resource_service is None:
            return None
        try:
            import pygame  # type: ignore[reportMissingImports]

            if self._provider_resources is not self._resource_service:
                self._provider = PygameResourceProvider(pygame, self._resource_service)
                self._provider_resources = self._resource_service
            return render_editor_frame_to_tk_image(
                frame,
                editor_render_context(editor_camera, width, height),
                width=width,
                height=height,
                resource_service=self._resource_service,
                resource_provider=self._provider,
                pygame_module=pygame,
                image_master=image_master,
            )
        except Exception:
            return None
