"""Normal-map generation for editor authoring.

This module owns the pure authoring pipeline that produces normal-map PNGs:
height-field derivation (Flat, Alpha Bevel, Luminance Emboss, Height Map),
height-to-tangent-normal conversion, PNG encoding, and atomic file writing.

It is an *editor* tool, not runtime resolution: ``runtime/normal_mapping.py``
keeps deterministic pairing only, and never generates files. This module never
imports a GUI toolkit, and Pillow is its only image dependency (NumPy is not
required).
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from expra_engine.filesystem import ResourceId
from expra_engine.runtime.normal_mapping import NormalYConvention, validate_normal_strength

__all__ = (
    "NormalMapGenerationPreset",
    "NormalMapGenerationSettings",
    "derive_height_field",
    "generate_normal_map",
    "generate_normal_map_png",
    "height_field_to_normal_rgb",
    "normal_map_output_id",
    "write_generated_normal",
)

_FLAT_NORMAL = (128, 128, 255)


class NormalMapGenerationPreset(StrEnum):
    FLAT = "flat"
    ALPHA_BEVEL = "alpha_bevel"
    ALPHA_SOBEL = "alpha_sobel"
    LUMINANCE_EMBOSS = "luminance_emboss"
    HEIGHT_MAP = "height_map"


@dataclass(frozen=True, slots=True)
class NormalMapGenerationSettings:
    """Immutable generation configuration for one normal-map candidate."""

    preset: NormalMapGenerationPreset | str = NormalMapGenerationPreset.ALPHA_BEVEL
    strength: float = 1.0
    y_convention: NormalYConvention | str = NormalYConvention.OPENGL
    # Alpha Bevel controls
    bevel_width: float = 2.0
    raised: bool = True
    # Luminance Emboss / Height Map controls
    pre_blur: float = 0.0
    invert_height: bool = False
    # Shared gradient border behavior (see height_field_to_normal_rgb)
    edge_mode: str = "clamp"

    def __post_init__(self) -> None:
        object.__setattr__(self, "preset", NormalMapGenerationPreset(self.preset))
        object.__setattr__(self, "y_convention", NormalYConvention(self.y_convention))
        object.__setattr__(self, "strength", validate_normal_strength(self.strength))
        for name, value in (("bevel_width", self.bevel_width), ("pre_blur", self.pre_blur)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be a non-negative finite number")
            object.__setattr__(self, name, float(value))
        if self.edge_mode not in {"clamp", "wrap", "mirror"}:
            raise ValueError("edge_mode must be 'clamp', 'wrap' or 'mirror'")


def _grayscale_luma(image: Image.Image) -> Image.Image:
    return image.convert("L")


def _alpha_mask(image: Image.Image) -> Image.Image | None:
    if image.mode in ("RGBA", "LA") or "A" in image.getbands():
        return image.getchannel("A")
    return None


def _normalized_rows(image: Image.Image) -> list[list[float]]:
    width, height = image.size
    data = image.convert("L").tobytes()
    return [
        [data[y * width + x] / 255.0 for x in range(width)]
        for y in range(height)
    ]


def derive_height_field(
    albedo: Image.Image,
    settings: NormalMapGenerationSettings,
    *,
    height_source: Image.Image | None = None,
) -> list[list[float]]:
    """Derive a scalar height field (rows of ``[0.0, 1.0]``) from the albedo.

    ``height_source`` is required only for the Height Map preset. Height fields
    are row-major with ``height[y][x]``; row ``0`` is the top of the image.
    """
    preset = settings.preset
    if preset is NormalMapGenerationPreset.FLAT:
        width, height = albedo.size
        return [[0.5] * width for _ in range(height)]

    if preset in (
        NormalMapGenerationPreset.ALPHA_BEVEL,
        NormalMapGenerationPreset.ALPHA_SOBEL,
    ):
        alpha = _alpha_mask(albedo)
        if alpha is None:
            raise ValueError("Alpha Bevel requires an albedo with an alpha channel")
        if settings.bevel_width > 0.0:
            alpha = alpha.filter(ImageFilter.GaussianBlur(settings.bevel_width))
        rows = _normalized_rows(alpha)
        if not settings.raised:
            rows = [[1.0 - value for value in row] for row in rows]
        return rows

    if preset is NormalMapGenerationPreset.HEIGHT_MAP:
        if height_source is None:
            raise ValueError("Height Map preset requires a height_source image")
        source = _grayscale_luma(height_source).resize(albedo.size)
    else:  # LUMINANCE_EMBOSS
        source = _grayscale_luma(albedo)

    if settings.pre_blur > 0.0:
        source = source.filter(ImageFilter.GaussianBlur(settings.pre_blur))
    rows = _normalized_rows(source)
    if settings.invert_height:
        rows = [[1.0 - value for value in row] for row in rows]
    return rows


def height_field_to_normal_rgb(
    height: Sequence[Sequence[float]],
    *,
    strength: float = 1.0,
    y_convention: NormalYConvention | str = NormalYConvention.OPENGL,
    edge_mode: str = "clamp",
    gradient_operator: str = "central",
) -> bytes:
    """Convert a scalar height field to packed RGB normal-map bytes.

    The tangent basis is Expra's canonical +X-right, +Y-up, +Z-toward-viewer.
    Gradients use central differences: ``gx`` is ``dH/dx`` toward image right,
    ``gy`` is ``dH/dy`` toward image *down* (row 0 is the top). The canonical
    surface normal is ``normalize(-gx * s, gy * s, 1)`` -- the ``gy`` sign is
    flipped because +Y-up is the opposite of image row order. DirectX output
    differs only by flipping the green/Y channel.
    """
    rows = [list(row) for row in height]
    if not rows or not rows[0]:
        raise ValueError("height field must be non-empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("height field rows must have equal width")
    amount = validate_normal_strength(strength)
    convention = NormalYConvention(y_convention)
    if edge_mode not in {"clamp", "wrap", "mirror"}:
        raise ValueError("edge_mode must be 'clamp', 'wrap' or 'mirror'")
    if gradient_operator not in {"central", "sobel"}:
        raise ValueError("gradient_operator must be 'central' or 'sobel'")

    def _neighbor(index: int, limit: int) -> int:
        if 0 <= index < limit:
            return index
        if edge_mode == "clamp":
            return 0 if index < 0 else limit - 1
        if edge_mode == "wrap":
            return index % limit
        # mirror
        period = 2 * (limit - 1) or 1
        reflected = index % period
        return reflected if reflected < limit else period - reflected

    output = bytearray(width * len(rows) * 3)
    for y in range(len(rows)):
        ym = _neighbor(y - 1, len(rows))
        yp = _neighbor(y + 1, len(rows))
        for x in range(width):
            xm = _neighbor(x - 1, width)
            xp = _neighbor(x + 1, width)
            if gradient_operator == "sobel":
                y_top = _neighbor(y - 1, len(rows))
                y_bottom = _neighbor(y + 1, len(rows))
                top_left = rows[y_top][_neighbor(x - 1, width)]
                top = rows[y_top][x]
                top_right = rows[y_top][_neighbor(x + 1, width)]
                middle_left = rows[y][_neighbor(x - 1, width)]
                middle_right = rows[y][_neighbor(x + 1, width)]
                bottom_left = rows[y_bottom][_neighbor(x - 1, width)]
                bottom = rows[y_bottom][x]
                bottom_right = rows[y_bottom][_neighbor(x + 1, width)]
                gx = (
                    -top_left + top_right - 2.0 * middle_left + 2.0 * middle_right
                    - bottom_left + bottom_right
                ) / 8.0
                gy = (
                    -top_left - 2.0 * top - top_right
                    + bottom_left + 2.0 * bottom + bottom_right
                ) / 8.0
            else:
                gx = (rows[y][xp] - rows[y][xm]) * 0.5
                gy = (rows[yp][x] - rows[ym][x]) * 0.5
            nx = -gx * amount
            ny = gy * amount
            if convention is NormalYConvention.DIRECTX:
                ny = -ny
            nz = 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if not math.isfinite(length) or length <= 1e-12:
                nx, ny, nz = 0.0, 0.0, 1.0
                length = 1.0
            nx, ny, nz = nx / length, ny / length, nz / length
            base = (y * width + x) * 3
            output[base] = round((nx * 0.5 + 0.5) * 255.0)
            output[base + 1] = round((ny * 0.5 + 0.5) * 255.0)
            output[base + 2] = round((nz * 0.5 + 0.5) * 255.0)
    return bytes(output)


def generate_normal_map(
    albedo: Image.Image,
    settings: NormalMapGenerationSettings,
    *,
    height_source: Image.Image | None = None,
) -> Image.Image:
    """Produce an RGB normal-map image for ``albedo``.

    Transparent albedo padding is forced to the flat normal ``(128, 128, 255)``
    so filtered sampling near sprite borders never picks up garbage (albedo
    alpha remains the coverage mask).
    """
    height = derive_height_field(albedo, settings, height_source=height_source)
    rgb = height_field_to_normal_rgb(
        height,
        strength=settings.strength,
        y_convention=settings.y_convention,
        edge_mode=settings.edge_mode,
        gradient_operator=(
            "sobel"
            if settings.preset is NormalMapGenerationPreset.ALPHA_SOBEL
            else "central"
        ),
    )
    result = Image.frombytes("RGB", albedo.size, rgb)
    alpha = _alpha_mask(albedo)
    if alpha is not None:
        flat = Image.new("RGB", albedo.size, _FLAT_NORMAL)
        result = Image.composite(result, flat, alpha)
    return result


def generate_normal_map_png(
    albedo: Image.Image,
    settings: NormalMapGenerationSettings,
    *,
    height_source: Image.Image | None = None,
) -> bytes:
    """Encode a generated normal map as PNG bytes."""
    image = generate_normal_map(albedo, settings, height_source=height_source)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def normal_map_output_id(base_texture_id: str) -> ResourceId:
    """Return the canonical ``<stem>_normal.png`` output ID for a base texture.

    ``ResourceId.parse`` already rejects path escape (``..``, absolute paths and
    backslashes), so the derived sibling is guaranteed to stay inside the
    resource namespace.
    """
    base = ResourceId.parse(base_texture_id)
    if base.scheme != "assets":
        raise ValueError("normal maps may only be generated into the assets namespace")
    source = Path(base.path)
    if source.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga"}:
        raise ValueError("base texture has an unsupported image extension")
    stem = source.stem
    if stem.casefold().endswith("_normal"):
        raise ValueError("base texture already looks like a normal map")
    return ResourceId(base.scheme, base.namespace, source.with_name(f"{stem}_normal.png").as_posix())


def _validate_png(png_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(png_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("generated normal map is not a valid image") from exc
    if image.mode not in ("RGB", "RGBA") or image.size[0] <= 0 or image.size[1] <= 0:
        raise ValueError("generated normal map must be a non-empty RGB or RGBA image")
    return image


def write_generated_normal(
    project: Any,
    base_texture_id: str,
    png_bytes: bytes,
    *,
    overwrite: bool = False,
) -> ResourceId:
    """Atomically write a generated normal-map PNG into the project's assets.

    Enforces, in order: a safe assets-namespace output ID, no overwrite by
    default, a temp-file write, a decode/validation pass, then an atomic
    promotion. A failed or cancelled write leaves any existing asset untouched.
    """
    output_id = normal_map_output_id(base_texture_id)
    _validate_png(png_bytes)

    assets_root = Path(project.assets_dir).resolve()
    destination = (assets_root / Path(output_id.path)).resolve()
    try:
        destination.relative_to(assets_root)
    except ValueError as exc:
        raise ValueError("generated normal map would escape the assets directory") from exc

    if destination.exists():
        if not overwrite:
            raise FileExistsError(f"normal map already exists: {output_id}")
        if not destination.is_file():
            raise FileExistsError(f"normal map target is not a file: {output_id}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".expra-normal-", suffix=".png", dir=destination.parent
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(png_bytes)
        if not overwrite:
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise FileExistsError(f"normal map already exists: {output_id}") from exc
            os.unlink(temporary)
            temporary = None
        else:
            os.replace(temporary, destination)
            temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    return output_id
