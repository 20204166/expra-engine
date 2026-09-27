"""Bounded Pygame compositor for renderer-neutral 2D light descriptors."""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from expra_engine.runtime.rendering import Color, LightDescriptor, RenderContext

__all__ = ("PygameLightingPass",)


class PygameLightingPass:
    """Add cached, soft point/cone light images after world draw operations."""

    _SOURCE_SIZE = 64
    _MAX_RADIUS_PIXELS = 384
    _MAX_CACHE_BYTES = 8 * 1024 * 1024
    _MAX_CACHE_ENTRIES = 24
    _MAX_LIGHTMAP_PIXELS = 16_777_216

    def __init__(self, pygame_module: Any) -> None:
        self.pygame = pygame_module
        self._cache: OrderedDict[tuple[object, ...], Any] = OrderedDict()
        self._cache_bytes = 0
        self._lightmap: Any | None = None
        self._lightmap_size: tuple[int, int] | None = None
        self.cache_hits = 0
        self.cache_misses = 0

    @property
    def supported(self) -> bool:
        return (
            callable(getattr(self.pygame, "Surface", None))
            and hasattr(self.pygame, "SRCALPHA")
            and hasattr(self.pygame, "BLEND_RGBA_ADD")
            and hasattr(self.pygame, "BLEND_RGBA_MULT")
            and callable(getattr(getattr(self.pygame, "transform", None), "smoothscale", None))
            and callable(getattr(getattr(self.pygame, "transform", None), "rotate", None))
        )

    @property
    def cache_entries(self) -> int:
        return len(self._cache)

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    def clear(self) -> None:
        self._cache.clear()
        self._cache_bytes = 0
        self._lightmap = None
        self._lightmap_size = None
        self.cache_hits = 0
        self.cache_misses = 0

    def render(
        self,
        lights: tuple[LightDescriptor, ...],
        *,
        surface: Any,
        context: RenderContext,
    ) -> bool:
        """Composite visible lights; return False without touching the target on setup failure."""
        visible = tuple(light for light in lights if light.is_visible(context))
        if not visible:
            return True
        if not self.supported or surface is None:
            return False
        try:
            width, height = surface.get_size()
            if width * height > self._MAX_LIGHTMAP_PIXELS:
                return False
            lightmap = self._get_lightmap((width, height))
            lightmap.fill((0, 0, 0, 0))
            for light in visible:
                image, center, origin = self._image_for(light, context)
                lightmap.blit(
                    image,
                    (round(center[0] - origin[0]), round(center[1] - origin[1])),
                    special_flags=self.pygame.BLEND_RGBA_ADD,
                )
            surface.blit(lightmap, (0, 0), special_flags=self.pygame.BLEND_RGBA_ADD)
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            return False
        return True

    def material_map(
        self,
        lights: tuple[LightDescriptor, ...],
        *,
        size: tuple[int, int],
        context: RenderContext,
        ambient: Color,
        diffuse: float,
        toon_steps: int | None,
    ) -> Any:
        """Build an SDL-composited illumination map for one response class."""
        if not self.supported:
            raise RuntimeError("Pygame lighting operations are unavailable")
        width, height = size
        if width <= 0 or height <= 0 or width * height > self._MAX_LIGHTMAP_PIXELS:
            raise ValueError("material light map dimensions are unsupported")
        lightmap = self.pygame.Surface(size, self.pygame.SRCALPHA, 32)
        lightmap.fill(
            (
                round(min(1.0, ambient.red) * 255),
                round(min(1.0, ambient.green) * 255),
                round(min(1.0, ambient.blue) * 255),
                255,
            )
        )
        for light in lights:
            if not light.is_visible(context):
                continue
            image, center, origin = self._image_for(
                light,
                context,
                diffuse=diffuse,
                toon_steps=toon_steps,
            )
            lightmap.blit(
                image,
                (round(center[0] - origin[0]), round(center[1] - origin[1])),
                special_flags=self.pygame.BLEND_RGBA_ADD,
            )
        return lightmap

    def _get_lightmap(self, size: tuple[int, int]) -> Any:
        if self._lightmap is None or self._lightmap_size != size:
            self._lightmap = self.pygame.Surface(size, self.pygame.SRCALPHA, 32)
            self._lightmap_size = size
        return self._lightmap

    def _image_for(
        self,
        light: LightDescriptor,
        context: RenderContext,
        *,
        diffuse: float = 1.0,
        toon_steps: int | None = None,
    ) -> tuple[Any, tuple[float, float], tuple[float, float]]:
        viewport = context.viewport
        camera = context.camera
        center = camera.project(light.position[:2], viewport)
        projected_radius = light.radius / camera.width * viewport.width
        radius_pixels = min(
            self._MAX_RADIUS_PIXELS,
            max(1, math.ceil(projected_radius)),
        )
        falloff_tenths = round(light.falloff * 10)
        cone_degrees = round(light.cone_angle) if light.kind == "spot" else 360
        screen_direction = 0.0
        if light.kind == "spot":
            angle = math.radians(light.direction_degrees)
            direction_point = camera.project(
                (light.position[0] + math.cos(angle), light.position[1] + math.sin(angle)),
                viewport,
            )
            screen_direction = round(
                math.degrees(
                    math.atan2(direction_point[1] - center[1], direction_point[0] - center[0])
                ),
                2,
            )
        intensity_rgb = tuple(
            round(min(1.0, channel * light.energy * diffuse * light.color.alpha) * 255)
            for channel in (light.color.red, light.color.green, light.color.blue)
        )
        geometry_key: tuple[str, int, int, int | None] = (
            light.kind,
            falloff_tenths,
            cone_degrees,
            toon_steps,
        )
        image_key = ("image", *geometry_key, radius_pixels, screen_direction, intensity_rgb)
        cached = self._cache.get(image_key)
        if cached is not None:
            self.cache_hits += 1
            self._cache.move_to_end(image_key)
            return cached, center, (cached.get_width() / 2, cached.get_height() / 2)

        geometry = self._geometry_for(geometry_key, radius_pixels)
        oriented = (
            self.pygame.transform.rotate(geometry, -screen_direction)
            if light.kind == "spot"
            else geometry
        )
        image = oriented.copy()
        image.fill(
            (*intensity_rgb, max(intensity_rgb)),
            special_flags=self.pygame.BLEND_RGBA_MULT,
        )
        self._remember(image_key, image)
        return image, center, (image.get_width() / 2, image.get_height() / 2)

    def _geometry_for(
        self,
        key: tuple[str, int, int, int | None],
        radius_pixels: int,
    ) -> Any:
        scaled_key = ("geometry", *key, radius_pixels)
        cached = self._cache.get(scaled_key)
        if cached is not None:
            self.cache_hits += 1
            self._cache.move_to_end(scaled_key)
            return cached
        mask_key = ("mask", *key)
        mask = self._cache.get(mask_key)
        if mask is None:
            self.cache_misses += 1
            _kind, falloff_tenths, cone_degrees, toon_steps = key
            mask = self._build_mask(
                int(falloff_tenths) / 10.0,
                int(cone_degrees),
                toon_steps=toon_steps,
            )
            self._remember(mask_key, mask)
        else:
            self.cache_hits += 1
            self._cache.move_to_end(mask_key)
        diameter = radius_pixels * 2 + 1
        geometry = self.pygame.transform.smoothscale(mask, (diameter, diameter))
        self._remember(scaled_key, geometry)
        return geometry

    def _remember(self, key: tuple[object, ...], image: Any) -> None:
        size_bytes = image.get_width() * image.get_height() * 4
        if size_bytes > self._MAX_CACHE_BYTES:
            return
        while self._cache and (
            len(self._cache) >= self._MAX_CACHE_ENTRIES
            or self._cache_bytes + size_bytes > self._MAX_CACHE_BYTES
        ):
            _, retired = self._cache.popitem(last=False)
            self._cache_bytes -= retired.get_width() * retired.get_height() * 4
        self._cache[key] = image
        self._cache_bytes += size_bytes

    def _build_mask(
        self,
        falloff: float,
        cone_degrees: int,
        *,
        toon_steps: int | None = None,
    ) -> Any:
        size = self._SOURCE_SIZE
        center = (size - 1) / 2
        base = self.pygame.Surface((size, size), self.pygame.SRCALPHA, 32)
        base.fill((0, 0, 0, 0))
        half_cone = math.radians(cone_degrees / 2)
        for y in range(size):
            dy = y - center
            for x in range(size):
                dx = x - center
                distance = math.hypot(dx, dy) / center
                if distance > 1.0:
                    continue
                if cone_degrees < 360:
                    angle = math.atan2(dy, dx)
                    if abs((angle + math.pi) % (2.0 * math.pi) - math.pi) > half_cone:
                        continue
                strength = (1.0 - distance) ** falloff
                if toon_steps is not None:
                    strength = math.floor(strength * (toon_steps - 1) + 0.5) / (toon_steps - 1)
                channel = round(255 * strength)
                base.set_at(
                    (x, y),
                    (channel, channel, channel, channel),
                )
        return base
