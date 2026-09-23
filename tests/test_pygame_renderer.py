"""Tests for the injected primitive Pygame renderer."""

import unittest
from math import radians
from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime import (
    Color,
    OrthographicCamera,
    PrimitiveDescriptor,
    PygameRenderer,
    PygameRenderFrame,
    RenderContext,
    RenderContractFrame,
    RendererCapabilities,
    RenderFrame,
    RenderItem,
    RenderPhase,
    Transform,
    Viewport,
)
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import MaterialDescriptor, NineSliceDescriptor, TextDescriptor
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureComponent,
)
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.ui import Button, GameCanvas, LayoutSpec
from expra_engine.runtime.ui import Viewport as UIViewport
from expra_engine.runtime.visual_components import PrimitiveComponent
from expra_engine.ui_model.geometry import Insets, Rect
from expra_engine.ui_model.nine_slice import NineSlice


class _FakeSurface:
    def __init__(self) -> None:
        self.blits: list[tuple[object, object]] = []

    def blit(self, rendered: object, position: object) -> None:
        self.blits.append((rendered, position))


class _FakeDraw:
    def __init__(self) -> None:
        self.rects: list[tuple[object, object, object]] = []
        self.circles: list[tuple[object, object, object, object]] = []
        self.lines: list[tuple[object, object, object, object]] = []
        self.polygons: list[tuple[object, object, object]] = []

    def rect(self, surface: object, color: object, rectangle: object, width: int = 0) -> None:
        self.rects.append((surface, color, rectangle, width))

    def circle(self, surface: object, color: object, center: object, radius: object) -> None:
        self.circles.append((surface, color, center, radius))

    def line(self, surface: object, color: object, start: object, end: object) -> None:
        self.lines.append((surface, color, start, end))

    def polygon(self, surface: object, color: object, points: object) -> None:
        self.polygons.append((surface, color, points))


class _FakeFont:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def render(self, text: str, antialias: bool, color: object) -> object:
        self.texts.append(text)
        return (text, antialias, color)

    def size(self, text: str) -> tuple[int, int]:
        return (len(text) * 10, 20)


class _FakeTexture:
    def get_size(self) -> tuple[int, int]:
        return (32, 16)


class _TintableTexture(_FakeTexture):
    def __init__(self) -> None:
        self.fill_calls: list[tuple[object, object]] = []
        self.copy_count = 0

    def copy(self) -> "_TintableTexture":
        self.copy_count += 1
        return _TintableTexture()

    def fill(self, color: object, *, special_flags: object) -> None:
        self.fill_calls.append((color, special_flags))


class _FakePygame:
    def __init__(self, font: _FakeFont) -> None:
        self.draw = _FakeDraw()
        self.font = SimpleNamespace(Font=lambda name, size: font)


class _ScreenSurface:
    def __init__(
        self,
        size: tuple[int, int] = (100, 100),
        *,
        events: list[str] | None = None,
        name: str = "surface",
    ) -> None:
        self._size = size
        self.events = events if events is not None else []
        self.name = name
        self.subsurfaces: list[tuple[int, int, int, int]] = []
        self.blits: list[tuple[object, object]] = []

    def get_size(self) -> tuple[int, int]:
        return self._size

    def copy(self) -> "_ScreenSurface":
        return _ScreenSurface(self._size, events=self.events, name=f"{self.name}.copy")

    def subsurface(self, rectangle: tuple[int, int, int, int]) -> "_ScreenSurface":
        self.subsurfaces.append(tuple(rectangle))
        self.events.append("capture")
        return _ScreenSurface(
            (rectangle[2], rectangle[3]),
            events=self.events,
            name=f"{self.name}.subsurface",
        )

    def blit(self, rendered: object, position: object) -> None:
        self.blits.append((rendered, position))
        self.events.append("blit:screen_texture")

    def get_rect(self, **kwargs: object) -> object:
        center = kwargs.get("center", (0, 0))
        assert isinstance(center, tuple)
        return SimpleNamespace(
            x=center[0] - self._size[0] // 2,
            y=center[1] - self._size[1] // 2,
            width=self._size[0],
            height=self._size[1],
        )


class _ScreenDraw(_FakeDraw):
    def rect(self, surface: object, color: object, rectangle: object, width: int = 0) -> None:
        super().rect(surface, color, rectangle, width)
        if not isinstance(surface, _ScreenSurface):
            return
        if color == (10, 14, 30):
            surface.events.append("clear")
        elif color == (255, 0, 0):
            surface.events.append("draw:background")
        elif color == (0, 0, 255):
            surface.events.append("draw:later")


class _ScreenTransform:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def scale(self, surface: _ScreenSurface, size: tuple[int, int]) -> _ScreenSurface:
        return _ScreenSurface(size, events=self.events, name="scaled")

    def smoothscale(self, surface: _ScreenSurface, size: tuple[int, int]) -> _ScreenSurface:
        return _ScreenSurface(size, events=self.events, name="smoothscaled")

    def rotate(self, surface: _ScreenSurface, angle: float) -> _ScreenSurface:
        return surface


class _ScreenPygame(_FakePygame):
    BLEND_RGBA_MULT = 7

    def __init__(self, font: _FakeFont, events: list[str]) -> None:
        super().__init__(font)
        self.draw = _ScreenDraw()
        self.transform = _ScreenTransform(events)


def _screen_effect_scene() -> Scene:
    scene = Scene("effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
    later = scene.create_entity("later", entity_id="later")
    later.add_component(PrimitiveComponent(fill=Color(0.0, 0.0, 1.0)))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent(width=2.0, height=2.0))
    return scene


class TestPygameRenderer(unittest.TestCase):
    def test_default_capabilities_do_not_claim_screen_support(self) -> None:
        capabilities = RendererCapabilities()

        self.assertFalse(capabilities.screen_capture)
        self.assertFalse(capabilities.screen_texture)
        self.assertFalse(capabilities.screen_texture_mipmaps)

    def test_renderer_reports_only_available_injected_screen_capabilities(self) -> None:
        font = _FakeFont()
        events: list[str] = []
        renderer = PygameRenderer(_ScreenPygame(font, events), None)

        self.assertFalse(renderer.capabilities.screen_capture)
        self.assertFalse(renderer.capabilities.screen_texture)
        self.assertFalse(renderer.capabilities.screen_texture_mipmaps)

        renderer.set_surface(_ScreenSurface(events=events))

        self.assertTrue(renderer.capabilities.screen_capture)
        self.assertTrue(renderer.capabilities.screen_texture)
        self.assertTrue(renderer.capabilities.screen_texture_mipmaps)

        limited = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        self.assertFalse(limited.capabilities.screen_capture)
        self.assertFalse(limited.capabilities.screen_texture)
        self.assertFalse(limited.capabilities.screen_texture_mipmaps)

    def test_screen_capabilities_require_the_operations_the_pipeline_uses(self) -> None:
        class _PartialSurface:
            def copy(self) -> object:
                return self

            def subsurface(self, _rectangle: object) -> object:
                return self

            def blit(self, _source: object, _destination: object) -> None:
                return None

        pygame = _FakePygame(_FakeFont())
        pygame.transform = SimpleNamespace(scale=lambda surface, size: surface)
        renderer = PygameRenderer(pygame, _PartialSurface())

        self.assertFalse(renderer.capabilities.screen_capture)
        self.assertFalse(renderer.capabilities.screen_texture)
        self.assertFalse(renderer.capabilities.screen_texture_mipmaps)

    def test_renderer_executes_capture_at_ordered_point_and_reuses_draw_logic(self) -> None:
        events: list[str] = []
        surface = _ScreenSurface(events=events)
        renderer = PygameRenderer(_ScreenPygame(_FakeFont(), events), surface)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(extract_render_frame(_screen_effect_scene()))

        self.assertEqual(
            events,
            ["clear", "draw:background", "capture", "draw:later", "blit:screen_texture"],
        )
        self.assertEqual(surface.subsurfaces, [(0, 0, 100, 100)])
        self.assertEqual(len(surface.blits), 1)

    def test_effect_frame_applies_canvas_modulation_to_contract_items_once(self) -> None:
        scene = _screen_effect_scene()
        background = scene.find_entity("background")
        assert background is not None
        background.add_component(CanvasModulateComponent((0.5, 0.5, 0.5, 0.5)))
        events: list[str] = []
        pygame = _ScreenPygame(_FakeFont(), events)
        renderer = PygameRenderer(pygame, _ScreenSurface(events=events))
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(extract_render_frame(scene))

        self.assertEqual(pygame.draw.rects[1][1], (128, 0, 0, 128))

    def test_ordinary_frames_bypass_screen_pipeline_and_keep_existing_draw_path(self) -> None:
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        def fail_if_executed(*args: object, **kwargs: object) -> None:
            raise AssertionError("ordinary frames must not execute the screen pipeline")

        renderer._screen_pipeline.execute = fail_if_executed  # type: ignore[method-assign]
        renderer.render(
            RenderContractFrame(
                (
                    RenderItem(
                        "ordinary",
                        PrimitiveDescriptor("rectangle", size=(2, 2)),
                        Transform(),
                    ),
                )
            )
        )

        self.assertEqual(len(renderer.pygame.draw.rects), 2)

    def test_screen_captures_clear_on_renderer_lifecycle_changes(self) -> None:
        events: list[str] = []
        renderer = PygameRenderer(
            _ScreenPygame(_FakeFont(), events),
            _ScreenSurface(events=events),
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        frame = RenderContractFrame(
            submissions=(
                RenderEffect(
                    BackBufferCopyRequest(
                        "capture",
                        "screen",
                        BackBufferCopyMode.VIEWPORT,
                    ),
                    RenderPhase.OPAQUE,
                    0,
                ),
            )
        )

        renderer.render(frame)
        self.assertEqual(renderer._screen_pipeline.capture_ids, ("screen",))
        renderer.resize(Viewport(0, 0, 80, 80))
        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

        renderer.render(frame)
        renderer.set_surface(_ScreenSurface((80, 80), events=events))
        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

        renderer.render(frame)
        renderer.stop()
        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

    def test_screen_captures_clear_before_an_ordinary_frame(self) -> None:
        events: list[str] = []
        renderer = PygameRenderer(
            _ScreenPygame(_FakeFont(), events),
            _ScreenSurface(events=events),
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        capture_frame = RenderContractFrame(
            submissions=(
                RenderEffect(
                    BackBufferCopyRequest(
                        "capture",
                        "screen",
                        BackBufferCopyMode.VIEWPORT,
                    ),
                    RenderPhase.OPAQUE,
                    0,
                ),
            )
        )

        renderer.render(capture_frame)
        self.assertEqual(renderer._screen_pipeline.capture_ids, ("screen",))
        renderer.render(RenderContractFrame())
        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

    def test_draws_renderer_neutral_runtime_ui_commands(self) -> None:
        font = _FakeFont()
        surface = _FakeSurface()
        renderer = PygameRenderer(_FakePygame(font), surface, font_provider=lambda name, size: font)
        canvas = GameCanvas()
        canvas.add(Button("play", text="Play", layout=LayoutSpec(size=(80, 30))))
        canvas.layout(UIViewport(200, 100))

        renderer.draw_ui_commands(canvas.draw_commands())

        self.assertEqual(font.texts, ["Play"])
        self.assertTrue(surface.blits)

    def test_injected_font_provider_draws_empty_multiline_wrapped_aligned_text(self) -> None:
        font = _FakeFont()
        surface = _FakeSurface()
        renderer = PygameRenderer(
            _FakePygame(font),
            surface,
            font_provider=lambda name, size: font,
        )
        renderer.start(RenderContext(Viewport(0, 0, 200, 100)))

        renderer.draw_text(
            TextDescriptor("one two\nthree", size=10, max_width=60, align="center"),
            (100, 10),
        )
        renderer.draw_text(TextDescriptor("", size=10), (0, 0))

        self.assertEqual([entry[0][0] for entry in surface.blits], ["one", "two", "three"])
        self.assertEqual(surface.blits[0][1], (85, 10))
        self.assertEqual(font.texts, ["one", "two", "three"])

    def test_text_measurement_is_provider_boundary_and_alpha_is_preserved(self) -> None:
        font = _FakeFont()
        renderer = PygameRenderer(
            _FakePygame(font),
            _FakeSurface(),
            font_provider=lambda name, size: font,
        )
        assert renderer.measure_text(TextDescriptor("abc", size=10)) == (30, 20)
        assert renderer._color(Color(1, 0, 0, 0.5), 0.5) == (255, 0, 0, 64)

    def test_nine_slice_consumes_resolved_geometry_and_resource_provider(self) -> None:
        pygame = _FakePygame(_FakeFont())
        surface = _FakeSurface()
        resource = object()
        renderer = PygameRenderer(
            pygame,
            surface,
            resource_provider=lambda resource_id: resource,
        )
        descriptor = NineSliceDescriptor(
            "panel",
            Rect(0, 0, 20, 20),
            NineSlice(Insets(2, 2, 2, 2)),
        )

        renderer.draw_nine_slice(descriptor, Color(1, 1, 1, 0.5))

        self.assertEqual(len(surface.blits), 9)
        self.assertTrue(all(entry[0] is resource for entry in surface.blits))

    def test_capabilities_explicitly_report_optional_support(self) -> None:
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()), _FakeSurface(), resource_provider=lambda _: object()
        )
        self.assertTrue(renderer.capabilities.text)
        self.assertTrue(renderer.capabilities.outline)
        self.assertTrue(renderer.capabilities.nine_slice)

    def test_primitive_applies_tint_and_outline_width(self) -> None:
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "styled",
            PrimitiveDescriptor("rectangle", size=(2, 2)),
            Transform(),
            material=MaterialDescriptor(
                color=Color(1, 1, 1),
                tint=Color(0, 1, 0),
                outline=Color(0, 0, 1),
                outline_width=2,
            ),
        )

        renderer.render(RenderContractFrame((item,)))

        self.assertEqual(renderer.pygame.draw.rects[1][1], (0, 255, 0))
        self.assertEqual(renderer.pygame.draw.rects[2][1], (0, 0, 255))
        self.assertEqual(renderer.pygame.draw.rects[2][3], 2)

    def test_contract_frame_applies_canvas_modulation_after_material_tint_once(self) -> None:
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "styled",
            PrimitiveDescriptor("rectangle", size=(2, 2)),
            Transform(),
            material=MaterialDescriptor(
                color=Color(0.8, 0.6, 0.4, 0.8),
                tint=Color(0.5, 0.5, 0.5, 0.5),
                outline=Color(0.4, 0.8, 1.0, 0.6),
                outline_width=2,
            ),
        )

        renderer.render(
            RenderContractFrame(
                (item,),
                modulation=Color(0.5, 0.5, 0.5, 0.5),
            )
        )

        self.assertEqual(renderer.pygame.draw.rects[1][1], (51, 38, 26, 51))
        self.assertEqual(renderer.pygame.draw.rects[2][1], (51, 102, 128, 76))

    def test_contract_frame_applies_canvas_modulation_to_text_alpha(self) -> None:
        font = _FakeFont()
        renderer = PygameRenderer(
            _FakePygame(font), _FakeSurface(), font_provider=lambda name, size: font
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "label",
            PrimitiveDescriptor("text", size=(2, 2)),
            Transform(),
            material=MaterialDescriptor(color=Color(1.0, 1.0, 1.0), opacity=0.8),
            text=TextDescriptor("hello", color=Color(0.5, 0.4, 0.3, 0.5)),
        )

        renderer.render(RenderContractFrame((item,), modulation=Color(0.5, 0.5, 0.5, 0.5)))

        assert renderer.surface.blits[-1][0][2] == (64, 51, 38, 51)

    def test_scene_extractor_to_pygame_renderer_uses_canonical_modulation(self) -> None:
        scene = Scene("night")
        entity = scene.create_entity("panel")
        entity.add_component(PrimitiveComponent(fill=Color(0.8, 0.6, 0.4)))
        entity.add_component(CanvasModulateComponent((0.5, 0.5, 0.5, 0.5)))
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(extract_render_frame(scene))

        assert renderer.pygame.draw.rects[1][1] == (82, 46, 20, 128)
    def test_render_frame_aliases_keep_protocol_and_legacy_hud_frames_distinct(self) -> None:
        self.assertIs(RenderFrame, PygameRenderFrame)
        self.assertIsNot(RenderContractFrame, PygameRenderFrame)

    def test_implements_renderer_lifecycle_and_reports_headless_capability(self) -> None:
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface())
        context = RenderContext(Viewport(0, 0, 800, 600))

        self.assertTrue(renderer.capabilities.primitive)
        self.assertTrue(renderer.capabilities.text)
        self.assertTrue(renderer.capabilities.resize)
        self.assertTrue(renderer.capabilities.headless)
        renderer.start(context)
        self.assertEqual(renderer.context, context)
        renderer.resize(Viewport(0, 0, 320, 240))
        self.assertEqual(renderer.context.viewport.width, 320)
        renderer.stop()
        self.assertIsNone(renderer.context)

    def test_contract_frame_draws_visible_items_in_phase_layer_depth_order(self) -> None:
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface())
        renderer.start(
            RenderContext(Viewport(0, 0, 100, 100), OrthographicCamera(width=10, height=10))
        )
        primitive = PrimitiveDescriptor("rectangle", size=(2, 2))
        frame = RenderContractFrame(
            (
                RenderItem(
                    "transparent",
                    primitive,
                    Transform(position=(3, 0, 0)),
                    phase=RenderPhase.TRANSPARENT,
                ),
                RenderItem("front", primitive, Transform(position=(2, 0, 1)), layer=1),
                RenderItem("back", primitive, Transform(position=(1, 0, -1)), layer=1),
                RenderItem("hidden", primitive, Transform(position=(100, 100, 0))),
            )
        )

        renderer.render(frame)

        drawn_rects = [entry[2] for entry in pygame.draw.rects[1:]]
        self.assertEqual(
            [rectangle.center for rectangle in drawn_rects], [(60, 50), (70, 50), (80, 50)]
        )

    def test_contract_frame_supports_headless_dummy_surface(self) -> None:
        pygame = SimpleNamespace(draw=SimpleNamespace(), font=SimpleNamespace(Font=lambda *_: None))
        renderer = PygameRenderer(pygame, None)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(RenderContractFrame())
        renderer.stop()

    def test_rotated_texture_uses_camera_and_transform_rotation(self) -> None:
        texture = _FakeTexture()
        calls: list[tuple[str, object]] = []
        pygame = _FakePygame(_FakeFont())
        pygame.transform = SimpleNamespace(
            rotate=lambda value, angle: (calls.append(("rotate", angle)) or value),
            smoothscale=lambda value, size: (calls.append(("scale", size)) or value),
        )
        renderer = PygameRenderer(pygame, _FakeSurface(), resource_provider=lambda _: texture)
        camera = OrthographicCamera()
        camera.rotation = radians(10.0)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100), camera))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(rotation=30.0),
            material=MaterialDescriptor(texture_id="ship"),
        )

        renderer.render(RenderContractFrame((item,)))

        self.assertEqual(calls[0], ("rotate", 20.0))
        self.assertEqual(calls[1], ("scale", (20, 10)))

    def test_texture_modulation_uses_copy_and_preserves_source_texture(self) -> None:
        texture = _TintableTexture()
        pygame = _FakePygame(_FakeFont())
        pygame.BLEND_RGBA_MULT = 123
        renderer = PygameRenderer(
            pygame,
            _FakeSurface(),
            resource_provider=lambda _: texture,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="ship", tint=Color(0.8, 0.6, 0.4)),
        )

        renderer.render(RenderContractFrame((item,), modulation=Color(0.5, 0.5, 0.5, 0.5)))

        assert texture.copy_count == 1
        assert texture.fill_calls == []
        assert renderer.surface.blits

    def test_neutral_canvas_modulation_preserves_existing_texture_rendering(self) -> None:
        texture = _TintableTexture()
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            _FakeSurface(),
            resource_provider=lambda _: texture,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="ship", tint=Color(0.2, 0.3, 0.4)),
        )

        renderer.render(RenderContractFrame((item,)))

        assert texture.copy_count == 0
        assert renderer.surface.blits[0][0] is texture

    def test_nine_slice_modulation_uses_backend_copy_when_supported(self) -> None:
        texture = _TintableTexture()
        pygame = _FakePygame(_FakeFont())
        pygame.BLEND_RGBA_MULT = 123
        renderer = PygameRenderer(
            pygame,
            _FakeSurface(),
            resource_provider=lambda _: texture,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        descriptor = NineSliceDescriptor(
            "panel",
            Rect(0, 0, 20, 20),
            NineSlice(Insets(2, 2, 2, 2)),
        )
        item = RenderItem(
            "panel",
            PrimitiveDescriptor("panel"),
            Transform(),
            nine_slice=descriptor,
        )

        renderer.render(RenderContractFrame((item,), modulation=Color(0.5, 0.5, 0.5, 0.5)))

        assert texture.copy_count == 1
        assert len(renderer.surface.blits) == 9

    def test_maps_transform_coordinates_into_arena_coordinates(self) -> None:
        scene = Scene("Arena")
        player = scene.create_entity("Player")
        player.add_tag("player")
        player.add_component(TransformComponent(x=25, y=50, rotation=0.0))
        surface = _FakeSurface()
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            surface,
            world_bounds=(0, 0, 100, 100),
            arena_bounds=(10, 20, 200, 100),
        )

        renderer.on_render(RenderFrame(scene))

        player_rect = renderer.pygame.draw.rects[1][2]
        self.assertEqual(player_rect.center, (60, 70))

    def test_legacy_renderer_can_consume_sampled_runtime_transform(self) -> None:
        scene = Scene("Arena")
        player = scene.create_entity("Player", entity_id="player")
        player.add_tag("player")
        player.add_component(TransformComponent(x=10.0))
        interpolator = TransformInterpolator()
        interpolator.begin_tick()
        interpolator.capture("player", Transform())
        interpolator.end_tick()
        interpolator.begin_tick()
        interpolator.capture("player", Transform(position=(10.0, 0.0, 0.0)))
        interpolator.end_tick()
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            _FakeSurface(),
            world_bounds=(0, 0, 100, 100),
            arena_bounds=(0, 0, 100, 100),
        )

        renderer.on_render(RenderFrame(scene, interpolator=interpolator, interpolation_fraction=0.5))

        assert renderer.pygame.draw.rects[1][2].center == (5, 0)

    def test_legacy_renderer_consumes_carried_canvas_modulation(self) -> None:
        scene = Scene("Arena")
        player = scene.create_entity("Player")
        player.add_tag("player")
        player.add_component(TransformComponent())
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())

        renderer.on_render(
            RenderFrame(
                scene,
                modulation=Color(0.5, 0.25, 0.75, 1.0),
            )
        )

        assert renderer.pygame.draw.rects[1][1] == (24, 56, 191)

    def test_legacy_scene_entities_use_active_camera_projection(self) -> None:
        scene = Scene("Camera")
        player = scene.create_entity("Player")
        player.add_tag("player")
        player.add_component(TransformComponent(x=10.0, y=5.0))
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            _FakeSurface(),
            world_bounds=(0, 0, 100, 100),
            arena_bounds=(0, 0, 200, 100),
        )
        renderer.start(
            RenderContext(Viewport(0, 0, 200, 100), OrthographicCamera(position=(10.0, 5.0, 0.0), width=20.0, height=10.0))
        )

        renderer.on_render(RenderFrame(scene))

        self.assertEqual(renderer.pygame.draw.rects[1][2].center, (100, 50))

    def test_rotated_legacy_entity_uses_polygon_draw_path(self) -> None:
        scene = Scene("Rotated")
        enemy = scene.create_entity("Enemy")
        enemy.add_tag("enemy")
        enemy.add_component(TransformComponent(rotation=45.0))
        renderer = PygameRenderer(_FakePygame(_FakeFont()), _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.on_render(RenderFrame(scene))

        self.assertEqual(len(renderer.pygame.draw.polygons), 1)
        self.assertEqual(len(renderer.pygame.draw.polygons[0][2]), 4)

    def test_draws_player_rectangle_and_target_circle_from_transforms(self) -> None:
        scene = Scene("Arena")
        player = scene.create_entity("Player")
        player.add_tag("player")
        player.add_component(TransformComponent(x=10, y=20, scale_x=2, scale_y=0.5))
        target = scene.create_entity("Target")
        target.add_tag("target")
        target.add_component(TransformComponent(x=80, y=70, scale_x=1.5, scale_y=1.5))
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface(), world_bounds=(0, 0, 100, 100))

        renderer.on_render(RenderFrame(scene))

        self.assertEqual(len(pygame.draw.rects), 2)  # arena and player
        self.assertEqual(pygame.draw.rects[1][2].size, (40, 10))
        self.assertEqual(pygame.draw.circles[0][2:], ((640, 420), 12))
        self.assertEqual(len(pygame.draw.lines), 1)

    def test_renders_score_and_status_hud(self) -> None:
        font = _FakeFont()
        surface = _FakeSurface()
        renderer = PygameRenderer(_FakePygame(font), surface)

        renderer.on_render(RenderFrame(None, score=3, status="WON"))

        self.assertEqual(font.texts, ["Score: 3", "WON"])
        self.assertEqual(len(surface.blits), 2)

    def test_rejects_non_positive_world_or_arena_dimensions(self) -> None:
        pygame = _FakePygame(_FakeFont())

        with self.assertRaises(ValueError):
            PygameRenderer(pygame, _FakeSurface(), world_bounds=(0, 0, 0, 100))
        with self.assertRaises(ValueError):
            PygameRenderer(pygame, _FakeSurface(), arena_bounds=(0, 0, -1, 100))

    def test_skips_zero_scale_and_uses_positive_size_for_negative_scale(self) -> None:
        scene = Scene("Arena")
        zero = scene.create_entity("Zero")
        zero.add_tag("player")
        zero.add_component(TransformComponent(scale_x=0, scale_y=0))
        negative = scene.create_entity("Negative")
        negative.add_tag("player")
        negative.add_component(TransformComponent(scale_x=-2, scale_y=-0.5))
        pygame = _FakePygame(_FakeFont())

        PygameRenderer(pygame, _FakeSurface()).on_render(RenderFrame(scene))

        self.assertEqual(len(pygame.draw.rects), 2)  # arena and negative-scale player
        self.assertEqual(pygame.draw.rects[1][2].size, (40, 10))

    def test_ignores_missing_and_disabled_entities_and_allows_off_screen_positions(self) -> None:
        scene = Scene("Arena")
        scene.create_entity("MissingTransform").add_tag("player")
        disabled = scene.create_entity("Disabled")
        disabled.add_tag("target")
        disabled.enabled = False
        disabled.add_component(TransformComponent())
        off_screen = scene.create_entity("Target")
        off_screen.add_component(TransformComponent(x=-50, y=150))
        pygame = _FakePygame(_FakeFont())

        PygameRenderer(pygame, _FakeSurface()).on_render(RenderFrame(scene))

        self.assertEqual(len(pygame.draw.circles), 1)
        self.assertEqual(pygame.draw.circles[0][2], (-400, 900))

    def test_continues_when_font_or_draw_operation_fails(self) -> None:
        class FailingDraw(_FakeDraw):
            def rect(self, surface: object, color: object, rectangle: object) -> None:
                raise RuntimeError("draw failed")

        class FailingFont(_FakeFont):
            def render(self, text: str, antialias: bool, color: object) -> object:
                raise RuntimeError("font failed")

        pygame = _FakePygame(FailingFont())
        pygame.draw = FailingDraw()

        PygameRenderer(pygame, _FakeSurface()).on_render(RenderFrame(None, status="SAFE"))

    def test_font_initialization_failure_keeps_renderer_usable(self) -> None:
        class BrokenFontModule:
            def Font(self, name: object, size: int) -> object:
                raise RuntimeError("font unavailable")

        pygame = _FakePygame(_FakeFont())
        pygame.font = BrokenFontModule()

        renderer = PygameRenderer(pygame, _FakeSurface())
        renderer.on_render(RenderFrame(None))

    def test_repeated_frames_only_draw_the_current_scene(self) -> None:
        first = Scene("First")
        first_target = first.create_entity("Target")
        first_target.add_component(TransformComponent(x=10, y=10))
        second = Scene("Second")
        second_target = second.create_entity("Target")
        second_target.add_component(TransformComponent(x=20, y=20))
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface())

        renderer.on_render(RenderFrame(first))
        renderer.on_render(RenderFrame(second))

        self.assertEqual(len(pygame.draw.circles), 2)
        self.assertEqual(pygame.draw.circles[0][2], (80, 60))
        self.assertEqual(pygame.draw.circles[1][2], (160, 120))


if __name__ == "__main__":
    unittest.main()
