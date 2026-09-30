from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from expra_engine.core.project import Project
from expra_engine.editor.normal_map_generation import (
    NormalMapGenerationPreset,
    NormalMapGenerationSettings,
    derive_height_field,
    generate_normal_map,
    generate_normal_map_png,
    height_field_to_normal_rgb,
    normal_map_output_id,
    write_generated_normal,
)


def _rgb(image: Image.Image) -> list[tuple[int, int, int]]:
    data = image.convert("RGB").tobytes()
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def test_flat_height_field_is_constant() -> None:
    albedo = Image.new("RGBA", (4, 3), (200, 0, 0, 255))
    settings = NormalMapGenerationSettings(preset=NormalMapGenerationPreset.FLAT)
    height = derive_height_field(albedo, settings)
    assert height == [[0.5] * 4] * 3


def test_flat_generator_produces_flat_normal() -> None:
    albedo = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    settings = NormalMapGenerationSettings(preset=NormalMapGenerationPreset.FLAT)
    image = generate_normal_map(albedo, settings)
    assert _rgb(image) == [(128, 128, 255)] * (8 * 8)


def test_ramp_to_the_right_tilts_normal_left() -> None:
    # Height increases toward +X (right): normal leans toward -X, so R < 128.
    height = [[x / 7.0 for x in range(8)] for _ in range(2)]
    rgb = height_field_to_normal_rgb(height, strength=1.0)
    image = Image.frombytes("RGB", (8, 2), rgb)
    pixels = _rgb(image)
    for r, g, b in pixels:
        assert r < 128
        assert g == pytest.approx(128, abs=2)
        assert b > 128


def test_ramp_downward_tilts_normal_up() -> None:
    # Height increases toward +row (down in image); +Y-up is the opposite, so
    # the canonical normal has N.y > 0 -> G > 128.
    height = [[y / 3.0] * 8 for y in range(4)]
    rgb = height_field_to_normal_rgb(height, strength=1.0)
    image = Image.frombytes("RGB", (8, 4), rgb)
    for r, g, b in _rgb(image):
        assert r == pytest.approx(128, abs=2)
        assert g > 128
        assert b > 128


def test_directx_differs_only_by_green_channel() -> None:
    height = [[(x + y) / 14.0 for x in range(8)] for y in range(4)]
    gl = Image.frombytes("RGB", (8, 4), height_field_to_normal_rgb(height, y_convention="opengl"))
    dx = Image.frombytes("RGB", (8, 4), height_field_to_normal_rgb(height, y_convention="directx"))
    gl_pixels = _rgb(gl)
    dx_pixels = _rgb(dx)
    for (r1, g1, b1), (r2, g2, b2) in zip(gl_pixels, dx_pixels, strict=True):
        assert r1 == r2
        assert b1 == b2
        assert g1 == 255 - g2


def test_alpha_bevel_keeps_transparent_padding_flat() -> None:
    # A 4x4 sprite with a 2x2 opaque block in the top-left; the rest transparent.
    albedo = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    albedo.paste((255, 0, 0, 255), (0, 0, 2, 2))
    settings = NormalMapGenerationSettings(
        preset=NormalMapGenerationPreset.ALPHA_BEVEL, bevel_width=0.0
    )
    image = generate_normal_map(albedo, settings)
    pixels = _rgb(image)
    for index, (x, y) in enumerate([(x, y) for y in range(4) for x in range(4)]):
        if albedo.getpixel((x, y))[3] == 0:
            assert pixels[index] == (128, 128, 255)


def test_alpha_bevel_produces_a_nonflat_bevel_on_the_edge() -> None:
    albedo = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    albedo.paste((255, 255, 255, 255), (2, 2, 6, 6))
    settings = NormalMapGenerationSettings(
        preset=NormalMapGenerationPreset.ALPHA_BEVEL, bevel_width=1.0
    )
    image = generate_normal_map(albedo, settings)
    # The edge ring must contain at least one pixel that is not flat.
    pixels = _rgb(image)
    assert any(pixel != (128, 128, 255) for pixel in pixels)


def test_alpha_sobel_uses_sobel_gradient_and_keeps_padding_flat() -> None:
    albedo = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
    albedo.paste((255, 255, 255, 255), (2, 2, 6, 6))
    settings = NormalMapGenerationSettings(
        preset=NormalMapGenerationPreset.ALPHA_SOBEL,
        strength=4.0,
        bevel_width=0.0,
    )

    pixels = _rgb(generate_normal_map(albedo, settings))

    assert pixels[0] == (128, 128, 255)
    # At the vertical silhouette edge, Sobel's normalized gradient is stronger
    # than the existing central-difference Alpha Bevel preset.
    assert pixels[3 * 8 + 2][0] < 32
    assert pixels[3 * 8 + 2][1] == pytest.approx(128, abs=2)


def test_alpha_sobel_is_available_alongside_existing_presets() -> None:
    assert NormalMapGenerationPreset.ALPHA_BEVEL in NormalMapGenerationPreset
    assert NormalMapGenerationPreset.ALPHA_SOBEL in NormalMapGenerationPreset


def test_generated_png_decodes_as_rgb() -> None:
    albedo = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    albedo.paste((255, 0, 0, 255), (1, 1, 5, 5))
    settings = NormalMapGenerationSettings(preset=NormalMapGenerationPreset.ALPHA_BEVEL)
    png = generate_normal_map_png(albedo, settings)
    decoded = Image.open(io.BytesIO(png))
    assert decoded.format == "PNG"
    assert decoded.mode == "RGB"
    assert decoded.size == (6, 6)


def test_normal_map_output_id_uses_canonical_sibling_name() -> None:
    assert str(normal_map_output_id("assets://oga/player_idle_0.png")) == (
        "assets://oga/player_idle_0_normal.png"
    )
    assert str(normal_map_output_id("assets://arena/wall.jpg")) == "assets://arena/wall_normal.png"


def test_normal_map_output_id_rejects_path_escape_and_wrong_scheme() -> None:
    with pytest.raises(ValueError):
        normal_map_output_id("assets://../evil.png")
    with pytest.raises(ValueError):
        normal_map_output_id("project://scripts/main.py")
    with pytest.raises(ValueError):
        normal_map_output_id("assets://tiles/stone_normal.png")


def test_write_generated_normal_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    project = Project.create("Gen", tmp_path / "project")
    (project.assets_dir / "tiles").mkdir(parents=True)
    (project.assets_dir / "tiles" / "stone.png").write_bytes(b"base")

    albedo = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    settings = NormalMapGenerationSettings(preset=NormalMapGenerationPreset.FLAT)
    png = generate_normal_map_png(albedo, settings)

    output_id = write_generated_normal(project, "assets://tiles/stone.png", png)
    assert str(output_id) == "assets://tiles/stone_normal.png"
    assert (project.assets_dir / "tiles" / "stone_normal.png").is_file()

    with pytest.raises(FileExistsError):
        write_generated_normal(project, "assets://tiles/stone.png", png)

    # Explicit overwrite succeeds.
    write_generated_normal(project, "assets://tiles/stone.png", png, overwrite=True)


def test_write_generated_normal_leaves_existing_asset_untouched_on_bad_input(
    tmp_path: Path,
) -> None:
    project = Project.create("Gen", tmp_path / "project")
    (project.assets_dir / "tiles").mkdir(parents=True)
    (project.assets_dir / "tiles" / "stone_normal.png").write_bytes(b"existing")
    with pytest.raises(ValueError):
        write_generated_normal(project, "assets://tiles/stone.png", b"not an image")
    assert (project.assets_dir / "tiles" / "stone_normal.png").read_bytes() == b"existing"
