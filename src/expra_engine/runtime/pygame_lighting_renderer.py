"""Pygame execution of renderer-neutral light and material responses."""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from expra_engine.observability import observe_stage
from expra_engine.runtime.material_lighting import LightingMode, MaterialLightResponse
from expra_engine.runtime.rendering import Color, RenderContext, RenderItem, TextDescriptor
from expra_engine.runtime.rendering import RenderFrame as ContractRenderFrame


class PygameLightingRenderMixin:
    @staticmethod
    def _material_lighting_active(frame: ContractRenderFrame) -> bool:
        configured = tuple(
            item.material.light_response
            for item in frame.items
            if item.material.light_response is not None
        )
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
                            value.get_width() * value.get_height() * 4 for value in maps.values()
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
            transform = item.visual_transform
            center_x, center_y = context.camera.project(transform.position[:2], context.viewport)
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
