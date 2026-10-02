"""Pygame execution of renderer-neutral light and material responses."""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from expra_engine.observability import observe_stage
from expra_engine.runtime.material_lighting import LightingMode, MaterialLightResponse
from expra_engine.runtime.normal_mapping import (
    NormalMapMode,
    NormalMapResolutionStatus,
)
from expra_engine.runtime.pygame_normal_mapping import (
    PygameNormalMapCache,
    apply_normal_basis,
    apply_normal_strength,
    sample_normal_channels,
    shade_normal_mapped_rgb,
)
from expra_engine.runtime.rendering import Color, RenderContext, RenderItem, TextDescriptor
from expra_engine.runtime.rendering import RenderFrame as ContractRenderFrame


class PygameLightingRenderMixin:
    @staticmethod
    def _material_lighting_active(frame: ContractRenderFrame) -> bool:
        configured = frame.material_light_responses
        if not configured:
            return False
        default = MaterialLightResponse()
        return (
            (bool(frame.lights) and frame.lighting_enabled)
            or frame.modulation != Color(1.0, 1.0, 1.0, 1.0)
            or any(response != default for response in configured)
        )

    def _do_lighting(self, frame, context, hits_b, misses_b):
        obs, lp = self._observer, self._lighting_pass
        if obs is not None:
            obs.increment("render:lighting", "lights_considered", len(frame.lights))
        with observe_stage(obs, "render:lighting:compose"):
            if not self.capabilities.lighting_2d or not lp.render(
                frame.lights,
                surface=self.surface,
                context=context,
            ):
                self._lighting_failed = True
            elif obs is not None:
                vl = len(frame.visible_lights(context))
                obs.increment("render:lighting", "lights_visible", vl)
                obs.increment("render:lighting", "light_cache_hits", lp.cache_hits - hits_b)
                obs.increment("render:lighting", "light_cache_misses", lp.cache_misses - misses_b)

    def _draw_material_item(
        self,
        item: RenderItem,
        surface: Any,
        frame: ContractRenderFrame,
        context: RenderContext,
        maps: OrderedDict[tuple[object, ...], Any],
    ) -> None:
        response = item.material.light_response or MaterialLightResponse()
        receiving = response.receives_light
        emission = response.emission
        if not receiving and emission == 0.0:
            self._draw_contract_item(
                item,
                surface,
                Color(1.0, 1.0, 1.0, frame.modulation.alpha),
                context,
            )
            return

        try:
            size = surface.get_size()
            bounds = self._material_bounds(item, context, size)
            if bounds is None:
                return
            scratch = self._material_scratch
            if scratch is None or scratch.get_size() != size:
                scratch = self.pygame.Surface(
                    size,
                    self.pygame.SRCALPHA,
                    32,
                )
                self._material_scratch = scratch
            scratch.fill((0, 0, 0, 0), bounds)
            alpha_modulation = frame.modulation.alpha if receiving else 1.0
            self._draw_contract_item(
                item,
                scratch,
                Color(1.0, 1.0, 1.0, alpha_modulation),
                context,
            )
            source = scratch.subsurface(bounds)
            emission_source = source.copy() if emission > 0.0 else None

            if receiving:
                ambient = Color(
                    frame.modulation.red * response.ambient_response,
                    frame.modulation.green * response.ambient_response,
                    frame.modulation.blue * response.ambient_response,
                    1.0,
                )
                local_lights = frame.lights if frame.lighting_enabled else ()
                toon_steps = response.toon_steps if response.mode is LightingMode.TOON else None
                normal_applied = self._apply_normal_lighting(
                    item,
                    source,
                    bounds,
                    local_lights,
                    context,
                    ambient,
                    response.diffuse,
                    toon_steps,
                )
                if not normal_applied:
                    # The cache exists for one RenderFrame only, so its light tuple
                    # is invariant and must not be repeated in each key: hashing a
                    # large descriptor tuple once per visual scales as visuals x lights.
                    map_key = (ambient, response.diffuse, toon_steps)
                    illumination = maps.get(map_key)
                    if illumination is None:
                        illumination = self._lighting_pass.material_map(
                            local_lights,
                            size=size,
                            context=context,
                            ambient=ambient,
                            diffuse=response.diffuse,
                            toon_steps=toon_steps,
                        )
                        map_bytes = size[0] * size[1] * 4
                        cache_budget = 8 * 1024 * 1024
                        while maps and (
                            len(maps) >= 8
                            or sum(
                                value.get_width() * value.get_height() * 4
                                for value in maps.values()
                            )
                            + map_bytes
                            > cache_budget
                        ):
                            maps.popitem(last=False)
                        if map_bytes > cache_budget:
                            maps.clear()
                        maps[map_key] = illumination
                    else:
                        maps.move_to_end(map_key)
                    source.blit(
                        illumination.subsurface(bounds),
                        (0, 0),
                        special_flags=self.pygame.BLEND_RGBA_MULT,
                    )

            if emission > 0.0:
                color = response.emission_color
                emission_layer = emission_source
                if emission_layer is not None:
                    emission_layer.fill(
                        (
                            round(color.red * emission * color.alpha * 255),
                            round(color.green * emission * color.alpha * 255),
                            round(color.blue * emission * color.alpha * 255),
                            255,
                        ),
                        special_flags=self.pygame.BLEND_RGBA_MULT,
                    )
                    source.blit(
                        emission_layer,
                        (0, 0),
                        special_flags=self.pygame.BLEND_RGB_ADD,
                    )
            surface.blit(source, bounds.topleft)
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            self._lighting_failed = True
            fallback = (
                frame.modulation if receiving else Color(1.0, 1.0, 1.0, frame.modulation.alpha)
            )
            self._draw_contract_item(item, surface, fallback, context)

    def _apply_normal_lighting(
        self,
        item: RenderItem,
        source: Any,
        bounds: Any,
        lights: tuple[Any, ...],
        context: RenderContext,
        ambient: Color,
        diffuse: float,
        toon_steps: int | None,
    ) -> bool:
        descriptor = item.material.normal_map
        base_texture_id = item.material.texture_id
        if descriptor is None or base_texture_id is None:
            return False
        if not self.capabilities.normal_mapping_2d:
            self._diagnostics.report(
                ("renderer", "normal-map", item.key, "unsupported"),
                "[NormalMap] Pygame normal mapping is unavailable for %s; using flat lighting",
                item.key,
            )
            return False

        normal_texture_id = descriptor.texture_id
        resolver = self._normal_map_resolver
        try:
            if resolver is not None:
                resolution = resolver.inspect(
                    base_texture_id,
                    descriptor.mode,
                    explicit_texture_id=descriptor.texture_id,
                )
                if resolution.status is not NormalMapResolutionStatus.RESOLVED:
                    raise ValueError(resolution.detail or resolution.status.value)
                normal_texture_id = resolution.normal_texture_id
                if normal_texture_id is not None:
                    resolver.register_dependency(base_texture_id, normal_texture_id)
            elif descriptor.mode is NormalMapMode.AUTO_PAIR:
                raise ValueError("auto-pair resolution requires a project resource service")
            if normal_texture_id is None:
                raise ValueError("normal texture is not resolved")

            normal_surface = self._resource_provider(normal_texture_id)
            albedo_surface = self._resource_provider(base_texture_id)
            if normal_surface is None or albedo_surface is None:
                raise ValueError("normal or albedo texture is unavailable")
            cache = self._normal_map_cache
            if cache is None:
                cache = PygameNormalMapCache(self.pygame)
                self._normal_map_cache = cache
            channels = cache.channels_for(
                normal_texture_id,
                normal_surface,
                descriptor.encoding,
                descriptor.y_convention,
            )
            normals = self._sample_item_normals(
                item,
                bounds,
                context,
                channels,
                albedo_surface.get_size(),
                descriptor.encoding,
                descriptor.strength,
            )
            world_x, world_y = self._world_coordinates(bounds, context)
            fields = tuple(
                (light, field)
                for light in lights
                if light.is_visible(context)
                for field in (self._normal_light_field(light, bounds, context),)
                if field is not None
            )
            source_rgb = self.pygame.surfarray.array3d(source)
            shaded = shade_normal_mapped_rgb(
                source_rgb,
                normals,
                world_x,
                world_y,
                fields,
                ambient=ambient,
                diffuse=diffuse,
                toon_steps=toon_steps,
            )
            pixels_alpha = self.pygame.surfarray.pixels_alpha
            alpha_view = pixels_alpha(source)
            source_alpha = alpha_view.copy()
            del alpha_view
            self.pygame.surfarray.blit_array(source, shaded)
            alpha_view = pixels_alpha(source)
            try:
                alpha_view[:, :] = source_alpha
            finally:
                del alpha_view
            observer = self._observer
            if observer is not None:
                observer.increment("render:normal-map", "mapped_visuals", 1)
                observer.increment(
                    "render:normal-map", "normal_shaded_pixels", bounds.width * bounds.height
                )
                observer.increment("render:normal-map", "overlapping_visible_lights", len(fields))
            self._diagnostics.resolve_prefix(("renderer", "normal-map", item.key))
            return True
        except Exception as exc:  # noqa: BLE001 - a bad normal is visual-local
            self._diagnostics.report(
                ("renderer", "normal-map", item.key, normal_texture_id or "unresolved"),
                "[NormalMap] Failed for %s: %s; using flat lighting",
                item.key,
                exc,
            )
            observer = self._observer
            if observer is not None:
                observer.increment("render:normal-map", "fallbacks", 1)
            return False

    def _sample_item_normals(
        self,
        item: RenderItem,
        bounds: Any,
        context: RenderContext,
        channels: Any,
        albedo_size: tuple[int, int],
        encoding: Any,
        strength: float,
    ) -> Any:
        np = __import__("numpy")
        transform = item.resolved_transform(context)
        center_x, center_y = item.project_point(context)
        rendered_width = round(
            abs(item.primitive.size[0] * transform.scale[0] / context.camera.width)
            * context.viewport.width
        )
        rendered_height = round(
            abs(item.primitive.size[1] * transform.scale[1] / context.camera.height)
            * context.viewport.height
        )
        if rendered_width <= 0 or rendered_height <= 0:
            raise ValueError("normal-mapped visual has zero projected size")
        screen_x = np.arange(bounds.left, bounds.right, dtype=np.float32) + np.float32(0.5)
        screen_y = np.arange(bounds.top, bounds.bottom, dtype=np.float32) + np.float32(0.5)
        dx = screen_x[:, None] - np.float32(center_x)
        dy = screen_y[None, :] - np.float32(center_y)
        angle = math.radians(transform.rotation - math.degrees(context.camera.rotation))
        cosine = np.float32(math.cos(angle))
        sine = np.float32(math.sin(angle))
        local_x = cosine * dx - sine * dy
        local_y = sine * dx + cosine * dy
        u = local_x / np.float32(rendered_width) + np.float32(0.5)
        v = local_y / np.float32(rendered_height) + np.float32(0.5)
        inside = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
        if item.sprite_flip_h:
            u = 1.0 - u
        if item.sprite_flip_v:
            v = 1.0 - v
        region = item.material.source_region
        if region is not None:
            albedo_width, albedo_height = albedo_size
            if albedo_width <= 0 or albedo_height <= 0:
                raise ValueError("albedo texture has invalid dimensions")
            u = (np.float32(region.x) + u * np.float32(region.width)) / np.float32(
                albedo_width
            )
            v = (np.float32(region.y) + v * np.float32(region.height)) / np.float32(
                albedo_height
            )
        sampled = sample_normal_channels(channels, u, v).astype(np.float32, copy=False)
        normals = apply_normal_strength(sampled, encoding, strength)
        normals = apply_normal_basis(
            normals,
            flip_h=item.sprite_flip_h,
            flip_v=item.sprite_flip_v,
            rotation_degrees=transform.rotation,
        )
        normals[~inside] = (0.0, 0.0, 1.0)
        return normals

    def _world_coordinates(self, bounds: Any, context: RenderContext) -> tuple[Any, Any]:
        np = __import__("numpy")
        viewport = context.viewport
        camera = context.camera
        screen_x = np.arange(bounds.left, bounds.right, dtype=np.float32) + np.float32(0.5)
        screen_y = np.arange(bounds.top, bounds.bottom, dtype=np.float32) + np.float32(0.5)
        rotated_x = (
            (screen_x[:, None] - viewport.x - viewport.width * 0.5)
            / viewport.width
            * camera.width
        )
        rotated_y = (
            (viewport.y + viewport.height * 0.5 - screen_y[None, :])
            / viewport.height
            * camera.height
        )
        cosine = np.float32(math.cos(camera.rotation))
        sine = np.float32(math.sin(camera.rotation))
        center_x = np.float32(camera.position[0] + camera.offset[0])
        center_y = np.float32(camera.position[1] + camera.offset[1])
        world_x = center_x + cosine * rotated_x - sine * rotated_y
        world_y = center_y + sine * rotated_x + cosine * rotated_y
        return (
            np.broadcast_to(world_x, (bounds.width, bounds.height)).astype(np.float32),
            np.broadcast_to(world_y, (bounds.width, bounds.height)).astype(np.float32),
        )

    def _normal_light_field(
        self,
        light: Any,
        bounds: Any,
        context: RenderContext,
    ) -> Any | None:
        np = __import__("numpy")
        image, center, origin = self._lighting_pass.normal_map_mask_for(light, context)
        image_left = round(center[0] - origin[0])
        image_top = round(center[1] - origin[1])
        overlap_left = max(bounds.left, image_left)
        overlap_top = max(bounds.top, image_top)
        overlap_right = min(bounds.right, image_left + image.get_width())
        overlap_bottom = min(bounds.bottom, image_top + image.get_height())
        if overlap_left >= overlap_right or overlap_top >= overlap_bottom:
            return None
        image_alpha = self.pygame.surfarray.array_alpha(image).astype(np.float32) / np.float32(255)
        field = np.zeros((bounds.width, bounds.height), dtype=np.float32)
        field[
            overlap_left - bounds.left : overlap_right - bounds.left,
            overlap_top - bounds.top : overlap_bottom - bounds.top,
        ] = image_alpha[
            overlap_left - image_left : overlap_right - image_left,
            overlap_top - image_top : overlap_bottom - image_top,
        ]
        return field

    def _material_bounds(
        self,
        item: RenderItem,
        context: RenderContext,
        size: tuple[int, int],
    ) -> Any | None:
        width, height = size
        if item.text is not None:
            text = item.text
            text_size = self.measure_text(
                TextDescriptor(
                    text.text,
                    text.font,
                    text.size,
                    text.color,
                    text.max_width,
                    text.align,
                )
            )
            center_x, center_y = item.project_point(context)
            text_x = round(center_x)
            if text.align == "center":
                text_x -= text_size[0] // 2
            elif text.align == "right":
                text_x -= text_size[0]
            left = text_x - 4
            top = round(center_y) - 4
            right = text_x + text_size[0] + 5
            bottom = round(center_y) + text_size[1] + 5
        elif item.nine_slice is not None:
            rect = item.nine_slice.rect
            geometry = item.nine_slice.geometry
            left = math.floor(rect.x - geometry.outset.left) - 4
            top = math.floor(rect.y - geometry.outset.bottom) - 4
            right = math.ceil(rect.x + rect.width + geometry.outset.right) + 5
            bottom = math.ceil(rect.y + rect.height + geometry.outset.top) + 5
        else:
            left_bound, top_bound, right_bound, bottom_bound = item._projected_bounds(context)
            left = math.floor(left_bound) - 4
            top = math.floor(top_bound) - 4
            right = math.ceil(right_bound) + 5
            bottom = math.ceil(bottom_bound) + 5
        left = max(0, left)
        top = max(0, top)
        right = min(width, right)
        bottom = min(height, bottom)
        if left >= right or top >= bottom:
            return None
        return self._rect((left, top, right - left, bottom - top))
