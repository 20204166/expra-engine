from __future__ import annotations

import pytest

from expra_engine.runtime.normal_mapping import (
    NormalMapEncoding,
    NormalYConvention,
    decode_normal_sample,
)
from expra_engine.runtime.pygame_normal_mapping import (
    PygameNormalMapCache,
    apply_normal_basis,
    decode_normal_pixels,
    sample_normal_channels,
    shade_normal_mapped_rgb,
)
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.rendering import Color, LightDescriptor

np = pytest.importorskip("numpy")


@pytest.mark.parametrize(
    ("encoding", "convention", "strength"),
    [
        (NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL, 1.0),
        (NormalMapEncoding.RGB_XYZ, NormalYConvention.DIRECTX, 2.0),
        (NormalMapEncoding.RG_XY, NormalYConvention.OPENGL, 1.0),
        (NormalMapEncoding.RG_XY, NormalYConvention.DIRECTX, 4.0),
    ],
)
def test_vectorized_decode_matches_scalar_reference(
    encoding: NormalMapEncoding,
    convention: NormalYConvention,
    strength: float,
) -> None:
    pixels = np.array(
        [
            [[128, 128, 255], [255, 128, 128]],
            [[128, 255, 128], [255, 255, 0]],
        ],
        dtype=np.uint8,
    )

    actual = decode_normal_pixels(pixels, encoding, convention, strength)

    expected = np.array(
        [
            [
                decode_normal_sample(*pixels[x, y], encoding=encoding, convention=convention, strength=strength)
                for y in range(pixels.shape[1])
            ]
            for x in range(pixels.shape[0])
        ],
        dtype=np.float32,
    )
    assert actual.shape == (2, 2, 3)
    assert actual.dtype == np.float32
    assert actual == pytest.approx(expected, abs=2e-6)


def test_vectorized_decode_keeps_surfarray_x_then_y_axis_order() -> None:
    pixels = np.zeros((2, 3, 3), dtype=np.uint8)
    pixels[1, 2] = (255, 128, 128)

    normals = decode_normal_pixels(pixels, NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL, 1.0)

    assert normals.shape == (2, 3, 3)
    assert normals[1, 2, 0] > 0.999
    assert normals[0, 2, 0] < 0.01


@pytest.mark.parametrize(
    "pixels",
    [
        np.zeros((2, 2), dtype=np.uint8),
        np.zeros((2, 2, 4), dtype=np.uint8),
        np.zeros((2, 2, 3), dtype=np.float32),
    ],
)
def test_vectorized_decode_rejects_non_rgb8_surfaces(pixels: np.ndarray) -> None:
    with pytest.raises(ValueError, match="uint8 RGB"):
        decode_normal_pixels(pixels, NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL, 1.0)


def test_normal_cache_reuses_surface_data_and_stays_within_configured_bounds() -> None:
    import pygame

    surface = pygame.Surface((2, 2), depth=32)
    surface.fill((128, 128, 255))
    cache = PygameNormalMapCache(pygame, max_entries=1, max_bytes=256, max_pixels=4)

    first = cache.channels_for("assets://a.png", surface, NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL)
    second = cache.channels_for("assets://a.png", surface, NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL)

    assert first is second
    assert cache.cache_entries == 1
    assert cache.cache_bytes <= 256


def test_normal_cache_rejects_images_over_pixel_limit() -> None:
    import pygame

    surface = pygame.Surface((2, 2), depth=32)
    cache = PygameNormalMapCache(pygame, max_pixels=3)

    with pytest.raises(ValueError, match="pixel limit"):
        cache.channels_for("assets://large.png", surface, NormalMapEncoding.RGB_XYZ, NormalYConvention.OPENGL)


def test_renderer_does_not_clear_an_injected_normal_cache_on_stop() -> None:
    import pygame

    surface = pygame.Surface((1, 1), depth=32)
    surface.fill((128, 128, 255))
    cache = PygameNormalMapCache(pygame)
    cache.channels_for(
        "assets://normal.png",
        surface,
        NormalMapEncoding.RGB_XYZ,
        NormalYConvention.OPENGL,
    )
    renderer = PygameRenderer(pygame, pygame.Surface((1, 1)), normal_map_cache=cache)

    renderer.stop()

    assert cache.cache_entries == 1


def test_normal_channel_sampling_uses_x_first_y_second_uv_coordinates() -> None:
    channels = np.zeros((2, 2, 3), dtype=np.float32)
    channels[1, 1] = (1.0, 0.0, 0.0)

    sample = sample_normal_channels(channels, np.array([0.75]), np.array([0.75]))

    assert sample.shape == (1, 3)
    assert sample[0, 0] == pytest.approx(1.0)


def test_normal_basis_applies_sprite_flips_before_world_rotation() -> None:
    normals = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)

    transformed = apply_normal_basis(
        normals,
        flip_h=True,
        flip_v=False,
        rotation_degrees=90.0,
    )

    assert transformed[0, 0] == pytest.approx((0.0, -1.0, 0.0), abs=1e-6)


def test_normal_shading_uses_world_light_direction_per_pixel() -> None:
    source = np.full((2, 1, 3), 100, dtype=np.uint8)
    normals = np.zeros((2, 1, 3), dtype=np.float32)
    normals[:, :, 0] = 1.0
    normals[:, :, 2] = 0.0
    world_x = np.zeros((2, 1), dtype=np.float32)
    world_y = np.zeros((2, 1), dtype=np.float32)
    attenuation = np.ones((2, 1), dtype=np.float32)
    right_light = LightDescriptor(
        "right", "point", (1.0, 0.0, 0.0), Color(1, 0, 0), 1.0, 2.0, 2.0, height=0.0
    )
    left_light = LightDescriptor(
        "left", "point", (-1.0, 0.0, 0.0), Color(0, 1, 0), 1.0, 2.0, 2.0, height=0.0
    )

    shaded = shade_normal_mapped_rgb(
        source,
        normals,
        world_x,
        world_y,
        ((right_light, attenuation), (left_light, attenuation)),
        ambient=Color(0, 0, 0),
        diffuse=1.0,
    )

    assert shaded.shape == source.shape
    assert shaded[0, 0, 0] == source[0, 0, 0]
    assert shaded[0, 0, 1] == 0


def test_normal_shading_flat_surface_uses_light_height_and_toon_quantizes_ndotl() -> None:
    source = np.full((1, 1, 3), 255, dtype=np.uint8)
    normals = np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32)
    world_x = np.zeros((1, 1), dtype=np.float32)
    world_y = np.zeros((1, 1), dtype=np.float32)
    attenuation = np.full((1, 1), 0.6, dtype=np.float32)
    light = LightDescriptor(
        "above", "point", (0.0, 0.0, 0.0), Color(1, 1, 1), 1.0, 2.0, 2.0, height=1.0
    )

    shaded = shade_normal_mapped_rgb(
        source,
        normals,
        world_x,
        world_y,
        ((light, attenuation),),
        ambient=Color(0, 0, 0),
        diffuse=1.0,
        toon_steps=3,
    )

    assert shaded[0, 0, 0] == 128


def test_auto_paired_normal_map_preserves_transparent_sprite_pixels(tmp_path) -> None:
    import pygame

    from expra_engine.core.project import Project
    from expra_engine.core.scene import Scene
    from expra_engine.runtime.canvas_effects import CanvasModulateComponent
    from expra_engine.runtime.material_component import MaterialComponent
    from expra_engine.runtime.normal_mapping import NormalMapResolver
    from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
    from expra_engine.runtime.render_extractor import extract_render_frame
    from expra_engine.runtime.visual_components import SpriteComponent
    from tests.support.pygame_renderer import make_renderer

    project = Project.create("Alpha normal map", tmp_path / "project")
    asset_dir = project.assets_dir / "oga"
    asset_dir.mkdir(parents=True)
    albedo = pygame.Surface((8, 8), pygame.SRCALPHA, 32)
    albedo.fill((162, 162, 162, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            albedo.set_at((x, y), (240, 40, 20, 255))
    normal = pygame.Surface((8, 8), pygame.SRCALPHA, 32)
    normal.fill((128, 128, 255, 255))
    pygame.image.save(albedo, asset_dir / "sprite.png")
    pygame.image.save(normal, asset_dir / "sprite_normal.png")

    scene = Scene("Alpha")
    scene.create_entity("modulation").add_component(
        CanvasModulateComponent((0.68, 0.73, 0.8, 1.0))
    )
    entity = scene.create_entity("sprite")
    entity.add_component(SpriteComponent("assets://oga/sprite.png", width=4, height=4))
    entity.add_component(MaterialComponent(normal_map_mode="auto_pair"))
    resources = project.resource_service()
    clear = (15, 20, 25)
    renderer, surface = make_renderer(
        pygame,
        (64, 64),
        clear_color=clear,
        camera_width=4.0,
        camera_height=4.0,
        resource_provider=PygameResourceProvider(pygame, resources),
        normal_map_resolver=NormalMapResolver(resources),
        pixel_art_mode=True,
    )
    renderer.render(extract_render_frame(scene))

    assert surface.get_at((8, 8))[:3] == clear
