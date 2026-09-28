"""Bounded NumPy-backed pixel data for the optional Pygame normal-map path."""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from expra_engine.runtime.normal_mapping import (
    NormalMapEncoding,
    NormalYConvention,
    validate_normal_strength,
)
from expra_engine.runtime.rendering import Color, LightDescriptor

__all__ = (
    "PygameNormalMapCache",
    "apply_normal_basis",
    "apply_normal_strength",
    "decode_normal_channels",
    "decode_normal_pixels",
    "sample_normal_channels",
    "shade_normal_mapped_rgb",
)


@dataclass(slots=True)
class _NormalCacheEntry:
    surface: Any
    channels: Any
    size_bytes: int


class PygameNormalMapCache:
    """Bounded cache of raw decoded tangent channels for provider-owned Surfaces."""

    def __init__(
        self,
        pygame_module: Any,
        *,
        max_entries: int = 16,
        max_bytes: int = 32 * 1024 * 1024,
        max_pixels: int = 2_000_000,
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0 or max_pixels <= 0:
            raise ValueError("normal cache bounds must be positive")
        self._pygame = pygame_module
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels
        self._entries: OrderedDict[tuple[object, ...], _NormalCacheEntry] = OrderedDict()
        self._cache_bytes = 0

    @property
    def cache_entries(self) -> int:
        return len(self._entries)

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    def clear(self) -> None:
        self._entries.clear()
        self._cache_bytes = 0

    def channels_for(
        self,
        texture_id: str,
        surface: Any,
        encoding: NormalMapEncoding | str,
        convention: NormalYConvention | str,
    ) -> Any:
        """Return source channels in canonical tangent space, evicting by bounded LRU."""
        map_encoding = _encoding(encoding)
        y_convention = _convention(convention)
        key = (texture_id, id(surface), map_encoding, y_convention)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached.channels

        width, height = surface.get_size()
        if width <= 0 or height <= 0 or width * height > self._max_pixels:
            raise ValueError("normal texture exceeds the configured pixel limit")
        surfarray = _surfarray(self._pygame)
        pixels = surfarray.array3d(surface)
        channels = decode_normal_channels(pixels, map_encoding, y_convention)
        size_bytes = channels.nbytes + width * height * 4
        if size_bytes > self._max_bytes:
            return channels
        while self._entries and (
            len(self._entries) >= self._max_entries
            or self._cache_bytes + size_bytes > self._max_bytes
        ):
            _, retired = self._entries.popitem(last=False)
            self._cache_bytes -= retired.size_bytes
        self._entries[key] = _NormalCacheEntry(surface, channels, size_bytes)
        self._cache_bytes += size_bytes
        return channels


def decode_normal_channels(
    pixels: Any,
    encoding: NormalMapEncoding | str,
    convention: NormalYConvention | str,
) -> Any:
    """Decode uint8 RGB data to unscaled tangent-space channel vectors."""
    np = _numpy()
    map_encoding = _encoding(encoding)
    y_convention = _convention(convention)
    array = np.asarray(pixels)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3:
        raise ValueError("normal pixels must be a uint8 RGB array")
    channels = array.astype(np.float32) * (2.0 / 255.0) - 1.0
    if y_convention is NormalYConvention.DIRECTX:
        channels[:, :, 1] *= -1.0
    if map_encoding is NormalMapEncoding.RG_XY:
        channels[:, :, 2] = 0.0
    return channels


def apply_normal_strength(
    channels: Any,
    encoding: NormalMapEncoding | str,
    strength: float,
) -> Any:
    """Scale tangent XY and normalize, exactly matching the scalar oracle."""
    np = _numpy()
    map_encoding = _encoding(encoding)
    amount = validate_normal_strength(strength)
    source = np.asarray(channels)
    if source.dtype != np.float32 or source.ndim < 2 or source.shape[-1] != 3:
        raise ValueError("normal channels must be a float32 array ending in three channels")
    if amount == 0.0:
        flat = np.zeros_like(source)
        flat[..., 2] = 1.0
        return flat

    result = source.copy()
    result[..., 0] *= amount
    result[..., 1] *= amount
    if map_encoding is NormalMapEncoding.RG_XY:
        xy_squared = result[..., 0] ** 2 + result[..., 1] ** 2
        over_unit = xy_squared > 1.0
        xy_length = np.sqrt(np.maximum(xy_squared, 1.0))
        result[..., 0] = np.where(over_unit, result[..., 0] / xy_length, result[..., 0])
        result[..., 1] = np.where(over_unit, result[..., 1] / xy_length, result[..., 1])
        xy_squared = result[..., 0] ** 2 + result[..., 1] ** 2
        reconstructed_z = np.sqrt(np.maximum(0.0, 1.0 - xy_squared))
        result[..., 2] = np.where(over_unit, 0.0, reconstructed_z)

    length = np.sqrt(np.sum(result * result, axis=-1))
    degenerate = length <= 1e-12
    safe_length = np.where(degenerate, 1.0, length)[..., None]
    result = result / safe_length
    if np.any(degenerate):
        result[degenerate] = (0.0, 0.0, 1.0)
    return result


def decode_normal_pixels(
    pixels: Any,
    encoding: NormalMapEncoding | str,
    convention: NormalYConvention | str,
    strength: float,
) -> Any:
    return apply_normal_strength(
        decode_normal_channels(pixels, encoding, convention), encoding, strength
    )


def sample_normal_channels(channels: Any, u: Any, v: Any) -> Any:
    """Bilinearly sample X-first/Y-second channels at normalized UV coordinates."""
    np = _numpy()
    source = np.asarray(channels)
    u_values = np.asarray(u, dtype=np.float32)
    v_values = np.asarray(v, dtype=np.float32)
    if source.dtype != np.float32 or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("normal channels must be a float32 X/Y/3 array")
    if u_values.shape != v_values.shape:
        raise ValueError("normal sample coordinates must have matching shapes")
    width, height = source.shape[:2]
    x = np.clip(u_values * width - 0.5, 0.0, width - 1.0)
    y = np.clip(v_values * height - 0.5, 0.0, height - 1.0)
    x0 = np.floor(x).astype(np.intp)
    y0 = np.floor(y).astype(np.intp)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    top = source[x0, y0] * (1.0 - fx) + source[x1, y0] * fx
    bottom = source[x0, y1] * (1.0 - fx) + source[x1, y1] * fx
    return top * (1.0 - fy) + bottom * fy


def apply_normal_basis(
    normals: Any,
    *,
    flip_h: bool,
    flip_v: bool,
    rotation_degrees: float,
) -> Any:
    """Transform tangent XY into world space using the sprite's authored basis."""
    np = _numpy()
    values = np.asarray(normals)
    if values.dtype != np.float32 or values.ndim < 2 or values.shape[-1] != 3:
        raise ValueError("normals must be a float32 array ending in three channels")
    angle = float(rotation_degrees)
    if not math.isfinite(angle):
        raise ValueError("normal basis rotation must be finite")
    result = values.copy()
    if flip_h:
        result[..., 0] *= -1.0
    if flip_v:
        result[..., 1] *= -1.0
    if angle:
        radians = math.radians(angle)
        cosine = np.float32(math.cos(radians))
        sine = np.float32(math.sin(radians))
        x_values = result[..., 0].copy()
        y_values = result[..., 1].copy()
        result[..., 0] = cosine * x_values - sine * y_values
        result[..., 1] = sine * x_values + cosine * y_values
    return result


def shade_normal_mapped_rgb(
    source_rgb: Any,
    normals: Any,
    world_x: Any,
    world_y: Any,
    light_fields: tuple[tuple[LightDescriptor, Any], ...],
    *,
    ambient: Color,
    diffuse: float,
    toon_steps: int | None = None,
) -> Any:
    """Shade one clipped material rectangle using per-pixel world-space N·L."""
    np = _numpy()
    pixels = np.asarray(source_rgb)
    normal_values = np.asarray(normals)
    x_values = np.asarray(world_x, dtype=np.float32)
    y_values = np.asarray(world_y, dtype=np.float32)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("source_rgb must be a uint8 RGB array")
    expected_shape = pixels.shape[:2]
    if (
        normal_values.dtype != np.float32
        or normal_values.shape != (*expected_shape, 3)
        or x_values.shape != expected_shape
        or y_values.shape != expected_shape
    ):
        raise ValueError("normal map shading inputs must have matching X/Y dimensions")
    if not isinstance(ambient, Color):
        raise TypeError("ambient must be a rendering.Color")
    diffuse_amount = float(diffuse)
    if not math.isfinite(diffuse_amount) or not 0.0 <= diffuse_amount <= 1.0:
        raise ValueError("diffuse must be between 0 and 1")
    if toon_steps is not None and (
        isinstance(toon_steps, bool) or not isinstance(toon_steps, int) or not 2 <= toon_steps <= 8
    ):
        raise ValueError("toon_steps must be an integer between 2 and 8")

    illumination = np.empty((*expected_shape, 3), dtype=np.float32)
    illumination[:] = (ambient.red, ambient.green, ambient.blue)
    for light, attenuation in light_fields:
        mask = np.asarray(attenuation, dtype=np.float32)
        if not isinstance(light, LightDescriptor) or mask.shape != expected_shape:
            raise ValueError("normal light fields must match the material bounds")
        dx = np.float32(light.position[0]) - x_values
        dy = np.float32(light.position[1]) - y_values
        dz = np.float32(light.height)
        length = np.sqrt(dx * dx + dy * dy + dz * dz)
        valid = length > np.float32(1e-12)
        inverse_length = np.divide(1.0, length, out=np.zeros_like(length), where=valid)
        lambert = np.maximum(
            0.0,
            normal_values[:, :, 0] * dx * inverse_length
            + normal_values[:, :, 1] * dy * inverse_length
            + normal_values[:, :, 2] * dz * inverse_length,
        )
        factor = mask * lambert
        if toon_steps is not None:
            factor = np.floor(factor * (toon_steps - 1) + 0.5) / (toon_steps - 1)
        energy = factor * (diffuse_amount * light.energy * light.color.alpha)
        illumination[:, :, 0] += energy * light.color.red
        illumination[:, :, 1] += energy * light.color.green
        illumination[:, :, 2] += energy * light.color.blue

    source = pixels.astype(np.float32) * (1.0 / 255.0)
    shaded = np.clip(source * np.clip(illumination, 0.0, 1.0), 0.0, 1.0)
    return np.rint(shaded * 255.0).astype(np.uint8)


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Pygame normal mapping requires the optional NumPy package") from exc
    return np


def _surfarray(pygame_module: Any) -> Any:
    try:
        module = pygame_module.surfarray
        array3d = getattr(module, "array3d", None)
    except (AttributeError, NotImplementedError) as exc:
        raise RuntimeError("Pygame surfarray support is unavailable") from exc
    if not callable(array3d):
        raise RuntimeError("Pygame surfarray support is unavailable")
    return module


def _encoding(value: NormalMapEncoding | str) -> NormalMapEncoding:
    try:
        return NormalMapEncoding(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported normal-map encoding") from exc


def _convention(value: NormalYConvention | str) -> NormalYConvention:
    try:
        return NormalYConvention(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported normal-map Y convention") from exc
