from __future__ import annotations

import math
from dataclasses import replace

import pygame

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.scene import Scene
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.pygame_lighting import PygameLightingPass
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, Viewport
from expra_engine.ui import editor_pixel_renderer
from expra_engine.ui.editor_pixel_renderer import EditorPixelRenderer
from expra_engine.ui.viewport_camera import ViewportCamera


def _light_frame(
    kind: str,
    *,
    rotation: float = 0.0,
    cone_angle: float = 60.0,
    color: tuple[float, float, float, float] = (1.0, 0.2, 0.1, 1.0),
    position: tuple[float, float] = (0.0, 0.0),
    energy: float = 1.0,
    radius: float = 3.0,
):
    scene = Scene("lighting")
    entity = scene.create_entity("light")
    entity.add_component(TransformComponent(x=position[0], y=position[1], rotation=rotation))
    entity.add_component(
        component_from_dict(
            {
                "type": "light_2d",
                "kind": kind,
                "color": list(color),
                "energy": energy,
                "radius": radius,
                "falloff": 2.0,
                "cone_angle": cone_angle,
            }
        )
    )
    return extract_render_frame(scene)


def _renderer(observer: ObservabilityWatcher | None = None):
    pygame.font.init()
    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0), observer=observer)
    renderer.start(
        RenderContext(
            Viewport(0, 0, 101, 101),
            OrthographicCamera(width=10.0, height=10.0),
        )
    )
    return renderer, surface


def test_point_light_adds_soft_local_color_and_adapts_to_runtime_capability() -> None:
    renderer, surface = _renderer()
    renderer.render(_light_frame("point"))

    assert renderer.capabilities.lighting_2d is True
    assert surface.get_at((50, 50)).r > 200
    assert 0 < surface.get_at((75, 50)).r < surface.get_at((50, 50)).r
    assert surface.get_at((90, 50)).r == 0


def test_lights_remain_visible_on_the_editors_transparent_pixel_surface() -> None:
    pygame.font.init()
    surface = pygame.Surface((101, 101), pygame.SRCALPHA, 32)
    renderer = PygameRenderer(pygame, surface, clear_color=None)
    renderer.start(RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera( width=10, height=10)))

    renderer.render(_light_frame("point"))

    assert surface.get_at((50, 50)).a > 0
    assert surface.get_at((90, 50)).a == 0


def test_spot_light_follows_entity_rotation_and_camera_rotation() -> None:
    renderer, surface = _renderer()
    frame = _light_frame("spot", rotation=0.0, cone_angle=60.0)
    renderer.render(frame)

    assert surface.get_at((70, 50)).r > 0
    assert surface.get_at((30, 50)).r == 0

    assert renderer.context is not None
    renderer.context.camera.rotation = math.pi / 2
    renderer.render(frame)

    assert surface.get_at((50, 70)).r > 0
    assert surface.get_at((70, 50)).r == 0


def test_spot_direction_retains_small_continuous_rotation_changes() -> None:
    renderer, surface = _renderer()
    frame = _light_frame("spot", rotation=0.0, cone_angle=4.0, radius=3.0)
    renderer.render(frame)
    unrotated_brightness = surface.get_at((70, 51)).r

    renderer.render(_light_frame("spot", rotation=-2.0, cone_angle=4.0, radius=3.0))
    assert surface.get_at((70, 51)).r > unrotated_brightness


def test_offscreen_lights_are_culled_by_camera_without_moving_them() -> None:
    frame = _light_frame("point", position=(100.0, 100.0))
    context = RenderContext(Viewport(0, 0, 101, 101), OrthographicCamera(width=10, height=10))

    assert frame.visible_lights(context) == ()
    assert frame.lights[0].position == (100.0, 100.0, 0.0)


def test_viewport_resize_replaces_only_the_render_size_light_surface() -> None:
    renderer, _surface = _renderer()
    frame = _light_frame("point")
    renderer.render(frame)
    assert renderer._lighting_pass._lightmap_size == (101, 101)

    viewport = Viewport(0, 0, 121, 81)
    renderer.set_surface(pygame.Surface((121, 81)))
    renderer.resize(viewport)
    renderer.render(frame)

    assert renderer._lighting_pass._lightmap_size == (121, 81)
    assert renderer.surface.get_at((60, 40)).r > 200


def test_world_space_light_radius_scales_with_camera_zoom() -> None:
    renderer, surface = _renderer()
    frame = _light_frame("point", radius=3.0)
    renderer.render(frame)
    assert surface.get_at((85, 50)).r == 0

    renderer.context.camera.zoom = 2.0
    renderer.render(frame)

    assert surface.get_at((85, 50)).r > 0
    assert frame.lights[0].position == (0.0, 0.0, 0.0)


def test_disabled_render_context_and_backend_failure_fall_back_unlit() -> None:
    renderer, surface = _renderer()
    frame = _light_frame("point")

    renderer.render(replace(frame, lighting_enabled=False))
    assert surface.get_at((50, 50)).r == 0

    renderer._lighting_pass.render = lambda *_args, **_kwargs: False
    renderer.render(frame)
    assert surface.get_at((50, 50)).r == 0
    assert renderer.draw_failed is False
    assert renderer._lighting_failed is True


def test_radial_texture_cache_is_bounded_and_released_on_renderer_stop() -> None:
    renderer, _surface = _renderer()
    for index in range(1, 32):
        renderer.render(
            _light_frame(
                "point",
                color=(index / 32, (32 - index) / 32, 0.5, 1.0),
            )
        )

    assert renderer._lighting_pass.cache_entries <= 24
    assert renderer._lighting_pass.cache_bytes <= 8 * 1024 * 1024
    renderer.stop()
    assert renderer._lighting_pass.cache_entries == 0
    assert renderer._lighting_pass.cache_bytes == 0


def test_lighting_observability_counts_per_frame_cache_activity() -> None:
    observer = ObservabilityWatcher()
    renderer, _surface = _renderer(observer)
    frame = _light_frame("point")
    renderer.render(frame)
    renderer.render(frame)

    metric = next(item for item in observer.snapshot().metrics if item.target == "render:lighting")
    counters = dict(metric.counters)
    assert counters["lights_considered"] == 2
    assert counters["lights_visible"] == 2
    assert counters["light_cache_hits"] == 1
    assert counters["light_cache_misses"] == 1


def test_renderer_instances_can_share_a_bounded_lighting_cache_owner() -> None:
    pygame.font.init()
    lighting_pass = PygameLightingPass(pygame)
    frame = _light_frame("point")
    for _ in range(2):
        surface = pygame.Surface((101, 101))
        renderer = PygameRenderer(
            pygame,
            surface,
            clear_color=(0, 0, 0),
            lighting_pass=lighting_pass,
        )
        renderer.start(
            RenderContext(
                Viewport(0, 0, 101, 101),
                OrthographicCamera(width=10.0, height=10.0),
            )
        )
        renderer.render(frame)

    assert lighting_pass.cache_misses == 1
    assert lighting_pass.cache_hits == 1


def test_editor_pixel_renderer_reuses_its_lighting_pass_across_frames(monkeypatch) -> None:
    passed_owners = []

    def fake_render(_frame, _context, **kwargs):
        passed_owners.append(kwargs.get("lighting_pass"))
        return object()

    monkeypatch.setattr(editor_pixel_renderer, "render_editor_frame_to_tk_image", fake_render)
    pixel_renderer = EditorPixelRenderer()
    camera = ViewportCamera((101, 101))
    master = object()
    frame = _light_frame("point")

    assert pixel_renderer.render(frame, camera, 101, 101, master) is not None
    assert pixel_renderer.render(frame, camera, 101, 101, master) is not None

    assert passed_owners[0] is pixel_renderer._lighting_pass
    assert passed_owners[1] is pixel_renderer._lighting_pass


def test_changing_light_energy_reuses_cached_radial_geometry() -> None:
    pygame.font.init()
    lighting_pass = PygameLightingPass(pygame)
    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(
        pygame,
        surface,
        clear_color=(0, 0, 0),
        lighting_pass=lighting_pass,
    )
    renderer.start(
        RenderContext(
            Viewport(0, 0, 101, 101),
            OrthographicCamera(width=10.0, height=10.0),
        )
    )
    renderer.render(_light_frame("point", energy=0.5))
    renderer.render(_light_frame("point", energy=1.0))

    assert lighting_pass.cache_misses == 1


def test_changing_light_radius_reuses_normalized_radial_shape() -> None:
    pygame.font.init()
    lighting_pass = PygameLightingPass(pygame)
    surface = pygame.Surface((101, 101))
    renderer = PygameRenderer(
        pygame,
        surface,
        clear_color=(0, 0, 0),
        lighting_pass=lighting_pass,
    )
    renderer.start(
        RenderContext(
            Viewport(0, 0, 101, 101),
            OrthographicCamera(width=10.0, height=10.0),
        )
    )
    for radius in (1.0, 2.0, 3.0):
        renderer.render(_light_frame("point", radius=radius))

    assert lighting_pass.cache_misses == 1
