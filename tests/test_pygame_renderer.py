"""Tests for the injected primitive Pygame renderer."""

import unittest
from math import radians
from types import SimpleNamespace
from typing import Any, cast

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime import (
    Color,
    OrthographicCamera,
    PrimitiveDescriptor,
    PygameRenderer,
    PygameRenderFrame,
    PygameResourceProvider,
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


class _ClearSurface(_FakeSurface):
    def __init__(self) -> None:
        super().__init__()
        self.fills: list[object] = []

    def fill(self, color: object) -> None:
        self.fills.append(color)


class _SourceTrackingSurface:
    def __init__(self) -> None:
        self.blit_calls: list[tuple[object, ...]] = []

    def blit(self, *args: object) -> None:
        self.blit_calls.append(args)


class _FakeDraw:
    def __init__(self) -> None:
        self.rects: list[tuple[object, object, object]] = []
        self.circles: list[tuple[object, object, object, object]] = []
        self.circle_widths: list[int] = []
        self.lines: list[tuple[object, object, object, object]] = []
        self.polygons: list[tuple[object, object, object]] = []
        self.polygon_widths: list[int] = []

    def rect(self, surface: object, color: object, rectangle: object, width: int = 0) -> None:
        self.rects.append((surface, color, rectangle, width))

    def circle(
        self,
        surface: object,
        color: object,
        center: object,
        radius: object,
        width: int = 0,
    ) -> None:
        self.circles.append((surface, color, center, radius))
        if width:
            self.circle_widths.append(width)

    def line(self, surface: object, color: object, start: object, end: object) -> None:
        self.lines.append((surface, color, start, end))

    def polygon(
        self,
        surface: object,
        color: object,
        points: object,
        width: int = 0,
    ) -> None:
        self.polygons.append((surface, color, points))
        if width:
            self.polygon_widths.append(width)


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


class _MutableResource:
    def __init__(self) -> None:
        self.payload = b"first"
        self.identity = "first"
        self.loads = 0

    def metadata(self, _resource_id: str) -> SimpleNamespace:
        return SimpleNamespace(size=len(self.payload), content_hash=self.identity)

    def read_bytes(self, _resource_id: str) -> bytes:
        return self.payload


class _DeletableResource:
    def __init__(self) -> None:
        self.deleted = False

    def metadata(self, _resource_id: str) -> SimpleNamespace:
        if self.deleted:
            raise FileNotFoundError("asset deleted")
        return SimpleNamespace(size=5, content_hash="asset")

    def read_bytes(self, _resource_id: str) -> bytes:
        if self.deleted:
            raise FileNotFoundError("asset deleted")
        return b"asset"


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
    def test_resource_provider_logs_png_decode_failure(self) -> None:
        resource = SimpleNamespace(
            metadata=lambda _resource_id: SimpleNamespace(size=3, content_hash="bad"),
            read_bytes=lambda _resource_id: b"bad",
        )

        def fail_decode(_stream: object) -> object:
            raise ValueError("invalid PNG")

        provider = PygameResourceProvider(
            SimpleNamespace(image=SimpleNamespace(load=fail_decode)), resource
        )

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            assert provider("assets://ship.png") is None

        assert any(
            "[Texture] Failed to decode assets://ship.png" in message for message in logs.output
        )
        self.assertEqual(provider.last_failure[0], "decode")  # type: ignore[index]

    def test_resource_provider_reports_resolution_and_read_failures(self) -> None:
        missing_metadata = SimpleNamespace(
            metadata=lambda _resource_id: (_ for _ in ()).throw(FileNotFoundError("missing")),
            read_bytes=lambda _resource_id: b"unused",
        )
        provider = PygameResourceProvider(
            SimpleNamespace(image=SimpleNamespace(load=lambda _stream: object())),
            missing_metadata,
        )

        self.assertIsNone(provider("assets://missing.png"))
        self.assertEqual(provider.last_failure[0], "resolve")  # type: ignore[index]

        unreadable = SimpleNamespace(
            metadata=lambda _resource_id: SimpleNamespace(size=1, content_hash="one"),
            read_bytes=lambda _resource_id: (_ for _ in ()).throw(OSError("unreadable")),
        )
        provider = PygameResourceProvider(
            SimpleNamespace(image=SimpleNamespace(load=lambda _stream: object())), unreadable
        )

        self.assertIsNone(provider("assets://unreadable.png"))
        self.assertEqual(provider.last_failure[0], "read")  # type: ignore[index]

    def test_resource_provider_clears_failure_after_success(self) -> None:
        resource = SimpleNamespace(
            metadata=lambda _resource_id: SimpleNamespace(size=1, content_hash="one"),
            read_bytes=lambda _resource_id: b"ok",
        )
        provider = PygameResourceProvider(
            SimpleNamespace(image=SimpleNamespace(load=lambda stream: stream.read())), resource
        )

        self.assertEqual(provider("assets://ship.png"), b"ok")
        self.assertIsNone(provider.last_failure)

    def test_resource_provider_deduplicates_persistent_failures_and_recovers(self) -> None:
        available = False

        def read_bytes(resource_id: str) -> bytes:
            if not available:
                raise OSError(f"unreadable {resource_id}")
            return b"ok"

        resource = SimpleNamespace(
            metadata=lambda _resource_id: SimpleNamespace(
                size=2, content_hash="stable" if available else "unavailable"
            ),
            read_bytes=read_bytes,
        )
        provider = PygameResourceProvider(
            SimpleNamespace(image=SimpleNamespace(load=lambda stream: stream.read())), resource
        )

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            for _ in range(100):
                self.assertIsNone(provider("assets://first.png"))
            self.assertIsNone(provider("assets://second.png"))
            available = True
            self.assertEqual(provider("assets://first.png"), b"ok")
            available = False
            self.assertIsNone(provider("assets://first.png"))

        self.assertEqual(len(logs.output), 3)
        self.assertIn("assets://first.png", logs.output[0])
        self.assertIn("assets://second.png", logs.output[1])
        self.assertIn("assets://first.png", logs.output[2])

    def test_successful_frame_resets_provider_failure_diagnostics(self) -> None:
        resources = SimpleNamespace(
            metadata=lambda _resource_id: SimpleNamespace(size=1, content_hash="same"),
            read_bytes=lambda _resource_id: (_ for _ in ()).throw(OSError("unreadable")),
        )
        pygame = SimpleNamespace(
            image=SimpleNamespace(load=lambda _stream: object()),
            draw=_FakeDraw(),
        )
        provider = PygameResourceProvider(pygame, resources)
        renderer = PygameRenderer(
            pygame, _ClearSurface(), resource_provider=provider, clear_color=None
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="ship"),
        )

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            renderer.render(RenderContractFrame((item,)))
            renderer.render(RenderContractFrame())
            renderer.render(RenderContractFrame((item,)))

        provider_errors = [message for message in logs.output if "Failed to read ship" in message]
        self.assertEqual(len(provider_errors), 2)

    def test_resource_provider_reloads_when_content_identity_changes(self) -> None:
        resources = _MutableResource()

        def load(stream: object) -> object:
            resources.loads += 1
            return stream.read()  # type: ignore[union-attr]

        pygame = SimpleNamespace(image=SimpleNamespace(load=load))
        provider = PygameResourceProvider(pygame, resources)

        first = provider("assets://ship.png")
        assert first == b"first"
        assert provider("assets://ship.png") is first
        self.assertEqual(resources.loads, 1)

        resources.payload = b"second"
        resources.identity = "second"

        second = provider("assets://ship.png")

        self.assertEqual(second, b"second")
        self.assertIsNot(second, first)
        self.assertEqual(resources.loads, 2)

    def test_resource_provider_drops_cached_texture_when_metadata_disappears(self) -> None:
        resources = _DeletableResource()
        pygame = SimpleNamespace(image=SimpleNamespace(load=lambda stream: stream.read()))
        provider = PygameResourceProvider(pygame, resources)

        first = provider("assets://ship.png")
        resources.deleted = True

        self.assertIsNone(provider("assets://ship.png"))
        self.assertIsNotNone(first)

    def test_transparent_clear_mode_preserves_editor_surface_alpha(self) -> None:
        surface = _ClearSurface()
        renderer = PygameRenderer(_FakePygame(_FakeFont()), surface, clear_color=None)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(RenderContractFrame())

        self.assertEqual(surface.fills, [(0, 0, 0, 0)])
        self.assertEqual(renderer.pygame.draw.rects, [])

    def test_clear_failure_marks_frame_incomplete_for_editor_fallback(self) -> None:
        class FailingClearSurface(_ClearSurface):
            def fill(self, color: object) -> None:
                raise RuntimeError(f"clear failed: {color!r}")

        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            FailingClearSurface(),
            clear_color=None,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(RenderContractFrame())

        self.assertTrue(renderer.draw_failed)

    def test_clear_failure_reports_the_backend_operation_once(self) -> None:
        class FailingClearSurface(_ClearSurface):
            def fill(self, color: object) -> None:
                raise RuntimeError(f"clear failed: {color!r}")

        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            FailingClearSurface(),
            clear_color=None,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            renderer.render(RenderContractFrame())
            renderer.render(RenderContractFrame())

        self.assertEqual(len(logs.output), 1)
        self.assertIn("could not clear target surface", logs.output[0])

    def test_missing_backend_surface_reports_the_capability_once(self) -> None:
        renderer = PygameRenderer(_FakePygame(_FakeFont()), None)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            renderer.render(RenderContractFrame())
            renderer.render(RenderContractFrame())

        self.assertEqual(len(logs.output), 1)
        self.assertIn("no target surface", logs.output[0])

    def test_missing_texture_marks_frame_incomplete_for_editor_fallback(self) -> None:
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            _FakeSurface(),
            resource_provider=lambda _texture_id: None,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="ship"),
        )

        renderer.render(RenderContractFrame((item,)))

        self.assertTrue(renderer.draw_failed)

    def test_backend_reset_allows_a_persistent_failure_to_log_again(self) -> None:
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            _FakeSurface(),
            resource_provider=lambda _texture_id: None,
        )
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="ship"),
        )

        with self.assertLogs("expra_engine.runtime.pygame_renderer", level="ERROR") as logs:
            renderer.render(RenderContractFrame((item,)))
            renderer.set_surface(_FakeSurface())
            renderer.render(RenderContractFrame((item,)))

        self.assertEqual(len(logs.output), 2)

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

    def test_render_plan_uses_rotated_primitive_path_before_capture(self) -> None:
        scene = _screen_effect_scene()
        background = scene.find_entity("background")
        assert background is not None
        background.add_component(TransformComponent(rotation=30.0))
        events: list[str] = []
        pygame = _ScreenPygame(_FakeFont(), events)
        renderer = PygameRenderer(pygame, _ScreenSurface(events=events))
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))

        renderer.render(extract_render_frame(scene))

        self.assertFalse(renderer.draw_failed)
        self.assertTrue(pygame.draw.polygons)
        self.assertIn("capture", events)

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

    def test_nine_slice_source_patches_ignore_destination_outset(self) -> None:
        surface = _SourceTrackingSurface()
        renderer = PygameRenderer(
            _FakePygame(_FakeFont()),
            surface,
            resource_provider=lambda _resource_id: _FakeTexture(),
        )
        descriptor = NineSliceDescriptor(
            "panel",
            Rect(0, 0, 20, 20),
            NineSlice(Insets(2, 2, 2, 2), outset=Insets(1, 1, 1, 1)),
        )

        renderer.draw_nine_slice(descriptor, Color(1, 1, 1))

        source_rects = [call[2] for call in surface.blit_calls]
        self.assertEqual(len(source_rects), 9)
        for source_rect in source_rects:
            self.assertGreaterEqual(source_rect.x, 0)
            self.assertGreaterEqual(source_rect.y, 0)
            self.assertLessEqual(source_rect.x + source_rect.width, 32)
            self.assertLessEqual(source_rect.y + source_rect.height, 16)

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

    def test_rotated_rectangle_uses_projected_polygon_for_fill_and_outline(self) -> None:
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface())
        camera = OrthographicCamera(width=10.0, height=10.0)
        camera.rotation = radians(15.0)
        renderer.start(
            RenderContext(
                Viewport(0, 0, 100, 100),
                camera,
            )
        )
        item = RenderItem(
            "rotated",
            PrimitiveDescriptor("rectangle", size=(2.0, 1.0)),
            Transform(position=(1.0, 0.5, 0.0), rotation=45.0),
            material=MaterialDescriptor(
                color=Color(1.0, 0.0, 0.0),
                outline=Color(0.0, 0.0, 1.0),
                outline_width=2,
            ),
        )

        renderer.render(RenderContractFrame((item,)))

        self.assertFalse(renderer.draw_failed)
        self.assertEqual(len(pygame.draw.polygons), 2)
        self.assertTrue(all(len(points) == 4 for _, _, points in pygame.draw.polygons))
        self.assertEqual(pygame.draw.polygon_widths, [2])

    def test_circle_and_point_outlines_use_canonical_draw_support(self) -> None:
        pygame = _FakePygame(_FakeFont())
        renderer = PygameRenderer(pygame, _FakeSurface())
        renderer.start(RenderContext(Viewport(0, 0, 100, 100)))
        outline = MaterialDescriptor(outline=Color(0.0, 0.0, 1.0), outline_width=1)

        renderer.render(
            RenderContractFrame(
                (
                    RenderItem(
                        "circle", PrimitiveDescriptor("circle", (2.0, 2.0)), Transform(), outline
                    ),
                    RenderItem("point", PrimitiveDescriptor("point"), Transform(), outline),
                )
            )
        )

        self.assertFalse(renderer.draw_failed)
        self.assertEqual(len(pygame.draw.circles), 4)
        self.assertEqual(pygame.draw.circle_widths, [1, 1])

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

        assert renderer.pygame.draw.rects[1][1] == (102, 76, 51, 128)

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
            rotate=lambda value, angle: calls.append(("rotate", angle)) or value,
            smoothscale=lambda value, size: calls.append(("scale", size)) or value,
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

        self.assertEqual(calls[0], ("scale", (20, 10)))
        self.assertEqual(calls[1], ("rotate", 20.0))

    def test_non_centered_sprite_uses_visual_transform_as_rotated_center(self) -> None:
        texture = _FakeTexture()
        pygame = _FakePygame(_FakeFont())
        pygame.transform = SimpleNamespace(
            smoothscale=lambda value, _size: value,
            rotate=lambda value, _angle: value,
        )
        surface = _FakeSurface()
        renderer = PygameRenderer(pygame, surface, resource_provider=lambda _: texture)
        camera = OrthographicCamera(width=10, height=10)
        renderer.start(RenderContext(Viewport(0, 0, 100, 100), camera))
        item = RenderItem(
            "sprite",
            PrimitiveDescriptor("sprite", size=(2.0, 1.0)),
            Transform(rotation=90.0),
            material=MaterialDescriptor(texture_id="ship"),
            sprite_centered=False,
        )

        renderer.render(RenderContractFrame((item,)))

        destination = surface.blits[0][1]
        expected = camera.project(
            (item.sprite_transform.position[0], item.sprite_transform.position[1]),
            RenderContext(Viewport(0, 0, 100, 100)).viewport,
        )
        self.assertEqual(destination.center, (round(expected[0]), round(expected[1])))

    def test_textured_non_sprite_draws_at_its_visual_transform(self) -> None:
        texture = _FakeTexture()
        pygame = _FakePygame(_FakeFont())
        cast(Any, pygame).transform = SimpleNamespace(smoothscale=lambda value, _size: value)
        surface = _FakeSurface()
        camera = OrthographicCamera(width=10, height=10)
        context = RenderContext(Viewport(0, 0, 100, 100), camera)
        renderer = PygameRenderer(pygame, surface, resource_provider=lambda _: texture)
        renderer.start(context)
        item = RenderItem(
            "textured-rectangle",
            PrimitiveDescriptor("rectangle", size=(2.0, 1.0)),
            Transform(),
            material=MaterialDescriptor(texture_id="assets://shape.png"),
            sprite_offset=(2.0, 0.0),
        )

        renderer.render(RenderContractFrame((item,)))

        expected = camera.project(
            (item.visual_transform.position[0], item.visual_transform.position[1]),
            context.viewport,
        )
        assert cast(Any, surface.blits[0][1]).center == (round(expected[0]), round(expected[1]))

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

        renderer.on_render(
            RenderFrame(scene, interpolator=interpolator, interpolation_fraction=0.5)
        )

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
            RenderContext(
                Viewport(0, 0, 200, 100),
                OrthographicCamera(position=(10.0, 5.0, 0.0), width=20.0, height=10.0),
            )
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


def test_rounded_rectangle_renders_real_pixels_fill_corner_and_outline() -> None:
    """Real Pygame pixels, not fake-draw call metadata: fill, rounded-corner
    transparency, and outline must all land where the geometry says they should.
    """
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        width, height = 200, 200
        surface = pygame.Surface((width, height), flags=pygame.SRCALPHA)
        renderer = PygameRenderer(pygame, surface, clear_color=None)
        camera = OrthographicCamera(width=20.0, height=20.0)
        renderer.start(RenderContext(Viewport(0, 0, width, height), camera))

        prim = PrimitiveDescriptor("rounded_rectangle", (10.0, 6.0), 1.5)
        material = MaterialDescriptor(
            color=Color(1.0, 0.0, 0.0, 1.0),
            outline=Color(0.0, 1.0, 0.0, 1.0),
            outline_width=2.0,
        )
        item = RenderItem("paddle", prim, Transform(position=(0.0, 0.0, 0.0)), material=material)

        renderer.render(RenderContractFrame((item,)))

        assert not renderer.draw_failed
        cx, cy = camera.project((0.0, 0.0), Viewport(0, 0, width, height))
        cx, cy = round(cx), round(cy)

        def px(x: int, y: int) -> tuple[int, int, int, int]:
            return tuple(surface.get_at((x, y)))

        # bbox: width_px=100, height_px=60, radius_px=15 -> x in [cx-50, cx+50], y in [cy-30, cy+30]
        assert px(cx, cy) == (255, 0, 0, 255)  # center: fill
        assert px(cx - 49, cy - 29) == (0, 0, 0, 0)  # bbox corner: rounded away, transparent
        assert px(cx - 90, cy - 90) == (0, 0, 0, 0)  # far outside bbox: transparent
        assert px(cx, cy - 29) == (0, 255, 0, 255)  # straight top edge: outline
        assert px(cx, cy - 25) == (255, 0, 0, 255)  # inside outline band: fill
    finally:
        pygame.quit()


def test_rounded_rectangle_rotation_preserves_visibility_and_sibling_items() -> None:
    """A rotated rounded rectangle must still produce real pixels, and must not
    trigger a whole-frame fallback that blanks an unrelated sibling item.
    """
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        width, height = 200, 200
        surface = pygame.Surface((width, height), flags=pygame.SRCALPHA)
        renderer = PygameRenderer(pygame, surface, clear_color=None)
        camera = OrthographicCamera(width=20.0, height=20.0)
        viewport = Viewport(0, 0, width, height)
        renderer.start(RenderContext(viewport, camera))

        rounded = RenderItem(
            "paddle",
            PrimitiveDescriptor("rounded_rectangle", (10.0, 6.0), 1.5),
            Transform(position=(0.0, 0.0, 0.0), rotation=45.0),
            material=MaterialDescriptor(color=Color(1.0, 0.0, 0.0, 1.0)),
        )
        sibling = RenderItem(
            "marker",
            PrimitiveDescriptor("rectangle", (2.0, 2.0)),
            Transform(position=(6.0, 6.0, 0.0)),
            material=MaterialDescriptor(color=Color(0.0, 0.0, 1.0, 1.0)),
        )

        renderer.render(RenderContractFrame((rounded, sibling)))

        assert not renderer.draw_failed

        def px(x: int, y: int) -> tuple[int, int, int, int]:
            return tuple(surface.get_at((x, y)))

        rcx, rcy = (round(v) for v in camera.project((0.0, 0.0), viewport))
        assert px(rcx, rcy) == (255, 0, 0, 255)  # rotated shape still fills its own center

        scx, scy = (round(v) for v in camera.project((6.0, 6.0), viewport))
        assert px(scx, scy) == (0, 0, 255, 255)  # sibling unaffected by the rotated draw
    finally:
        pygame.quit()


if __name__ == "__main__":
    unittest.main()
