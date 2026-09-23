"""End-to-end coverage for scene extraction through the Pygame screen pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from expra_engine.core.scene import Scene
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameRenderFrame
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.render_pipeline import (
    CaptureScreenOp,
    DrawItemOp,
    DrawScreenTextureOp,
    RenderPlanBuilder,
)
from expra_engine.runtime.rendering import (
    Color,
    OrthographicCamera,
    RenderContext,
    RenderFrame,
    RenderPhase,
    Viewport,
)
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    ScreenTextureComponent,
)
from expra_engine.runtime.visual_components import PrimitiveComponent


@dataclass(frozen=True)
class _Rect:
    x: int
    y: int
    width: int
    height: int


class _Surface:
    def __init__(
        self,
        size: tuple[int, int] = (100, 100),
        *,
        events: list[str] | None = None,
        name: str = "surface",
        content: object | None = None,
        capture_contents: list[_Surface] | None = None,
        capture_region: bool = False,
    ) -> None:
        self._size = size
        self.events = events if events is not None else []
        self.name = name
        self.content = content
        self.capture_contents = capture_contents if capture_contents is not None else []
        self._capture_region = capture_region
        self.subsurfaces: list[tuple[int, int, int, int]] = []
        self.blits: list[tuple[object, object]] = []
        self.fills: list[tuple[object, object]] = []

    def get_size(self) -> tuple[int, int]:
        return self._size

    def copy(self) -> _Surface:
        copied = _Surface(
            self._size,
            events=self.events,
            name=f"{self.name}.copy",
            content=self.content,
            capture_contents=self.capture_contents,
        )
        if self._capture_region:
            self.capture_contents.append(copied)
        return copied

    def subsurface(self, rectangle: tuple[int, int, int, int]) -> _Surface:
        rectangle = tuple(rectangle)
        self.subsurfaces.append(rectangle)
        self.events.append("capture")
        return _Surface(
            (rectangle[2], rectangle[3]),
            events=self.events,
            name=f"{self.name}.subsurface",
            content=self.content,
            capture_contents=self.capture_contents,
            capture_region=True,
        )

    def blit(self, source: object, destination: object) -> None:
        self.blits.append((source, destination))
        self.events.append("blit:screen_texture")
        if isinstance(source, _Surface):
            self.content = source.content

    def fill(self, value: object, special_flags: object = None) -> None:
        self.fills.append((value, special_flags))

    def get_rect(self, **kwargs: object) -> _Rect:
        center = kwargs.get("center", (0, 0))
        assert isinstance(center, tuple)
        return _Rect(
            center[0] - self._size[0] // 2,
            center[1] - self._size[1] // 2,
            self._size[0],
            self._size[1],
        )


class _Draw:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.rects: list[tuple[object, object, object, int]] = []

    def rect(
        self,
        surface: object,
        color: object,
        rectangle: object,
        width: int = 0,
    ) -> None:
        self.rects.append((surface, color, rectangle, width))
        if not isinstance(surface, _Surface):
            return
        surface.content = color
        labels = {
            (10, 14, 30): "clear",
            (255, 0, 0): "draw:background",
            (128, 0, 0, 128): "draw:background",
            (0, 0, 255): "draw:later",
        }
        label = labels.get(color)
        if label is not None:
            self.events.append(label)


class _Transform:
    def __init__(self) -> None:
        self.scales: list[tuple[_Surface, tuple[int, int]]] = []
        self.smoothscales: list[tuple[_Surface, tuple[int, int]]] = []
        self.rotations: list[tuple[_Surface, float]] = []

    @staticmethod
    def _scaled(surface: _Surface, size: tuple[int, int], name: str) -> _Surface:
        return _Surface(
            size,
            events=surface.events,
            name=name,
            content=surface.content,
            capture_contents=surface.capture_contents,
        )

    def scale(self, surface: _Surface, size: tuple[int, int]) -> _Surface:
        self.scales.append((surface, size))
        return self._scaled(surface, size, "scaled")

    def smoothscale(self, surface: _Surface, size: tuple[int, int]) -> _Surface:
        self.smoothscales.append((surface, size))
        return self._scaled(surface, size, "smoothscaled")

    def rotate(self, surface: _Surface, angle: float) -> _Surface:
        self.rotations.append((surface, angle))
        return surface


class _Font:
    def render(self, text: str, antialias: bool, color: object) -> tuple[str, bool, object]:
        return (text, antialias, color)

    def size(self, text: str) -> tuple[int, int]:
        return (len(text) * 10, 20)


class _Pygame:
    BLEND_RGBA_MULT = 7

    def __init__(self, events: list[str]) -> None:
        self.draw = _Draw(events)
        self.transform = _Transform()
        font = _Font()
        self.font = SimpleNamespace(Font=lambda _name, _size: font)


def _context() -> RenderContext:
    return RenderContext(
        Viewport(0, 0, 100, 100),
        OrthographicCamera(width=10.0, height=10.0),
    )


def _renderer(
    events: list[str],
    surface: _Surface | None = None,
) -> tuple[PygameRenderer, _Pygame, _Surface]:
    surface = surface or _Surface(events=events)
    pygame = _Pygame(events)
    renderer = PygameRenderer(pygame, surface)
    renderer.start(_context())
    return renderer, pygame, surface


def _scene_with_explicit_capture(*, recapture: bool = False) -> Scene:
    scene = Scene("effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))

    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(
        BackBufferCopyComponent(
            copy_mode=BackBufferCopyMode.VIEWPORT,
            capture_id="screen",
        )
    )

    later = scene.create_entity("later", entity_id="later")
    later.add_component(PrimitiveComponent(fill=Color(0.0, 0.0, 1.0)))

    if recapture:
        second_capture = scene.create_entity("recapture", entity_id="recapture")
        second_capture.add_component(
            BackBufferCopyComponent(
                copy_mode=BackBufferCopyMode.VIEWPORT,
                capture_id="screen",
            )
        )

    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent(capture_id="screen", width=2.0, height=2.0))
    return scene


def test_real_scene_executes_clear_draw_capture_draw_and_sample_in_order() -> None:
    scene = _scene_with_explicit_capture()
    frame = extract_render_frame(scene)
    context = _context()

    assert [item.key for item in frame.items] == ["background", "later"]
    plan = RenderPlanBuilder.from_frame(frame, context)
    assert [type(operation) for operation in plan.operations] == [
        DrawItemOp,
        CaptureScreenOp,
        DrawItemOp,
        DrawScreenTextureOp,
    ]

    events: list[str] = []
    renderer, _pygame, _surface = _renderer(events)
    renderer.render(frame)

    assert events == [
        "clear",
        "draw:background",
        "capture",
        "draw:later",
        "blit:screen_texture",
    ]


def test_legacy_payload_does_not_clear_the_ordered_screen_texture_result() -> None:
    scene = _scene_with_explicit_capture()
    extracted = extract_render_frame(scene)
    frame = RenderFrame(
        extracted.items,
        payload=PygameRenderFrame(active_scene=scene),
        modulation=extracted.modulation,
        submissions=extracted.submissions,
    )
    events: list[str] = []
    renderer, _pygame, surface = _renderer(events)

    renderer.render(frame)

    assert events.count("clear") == 1
    assert surface.content == (255, 0, 0)


def test_explicit_recapture_replaces_slot_without_mutating_frozen_pixels() -> None:
    scene = _scene_with_explicit_capture(recapture=True)
    events: list[str] = []
    renderer, _pygame, surface = _renderer(events)

    renderer.render(extract_render_frame(scene))

    first, second = surface.capture_contents[:2]
    current = renderer._screen_pipeline.snapshot("screen")
    assert current is not None
    assert current.base is second
    assert current.base is not first
    assert first.content == (255, 0, 0)
    assert second.content == (0, 0, 255)
    assert events == [
        "clear",
        "draw:background",
        "capture",
        "draw:later",
        "capture",
        "blit:screen_texture",
    ]


def test_named_consumers_auto_capture_independent_slots() -> None:
    scene = Scene("named effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))
    left = scene.create_entity("left", entity_id="left")
    left.add_component(
        ScreenTextureComponent(capture_id="left", phase=RenderPhase.OPAQUE, width=2.0, height=2.0)
    )
    later = scene.create_entity("later", entity_id="later")
    later.add_component(PrimitiveComponent(fill=Color(0.0, 0.0, 1.0)))
    right = scene.create_entity("right", entity_id="right")
    right.add_component(
        ScreenTextureComponent(capture_id="right", phase=RenderPhase.OPAQUE, width=2.0, height=2.0)
    )

    frame = extract_render_frame(scene)
    plan = RenderPlanBuilder.from_frame(frame, _context())
    captures = [
        (operation.request.capture_id, operation.automatic)
        for operation in plan.operations
        if isinstance(operation, CaptureScreenOp)
    ]
    assert captures == [("left", True), ("right", True)]

    events: list[str] = []
    renderer, _pygame, surface = _renderer(events)
    renderer.render(frame)

    left_snapshot = renderer._screen_pipeline.snapshot("left")
    right_snapshot = renderer._screen_pipeline.snapshot("right")
    assert renderer._screen_pipeline.capture_ids == ("left", "right")
    assert left_snapshot is not None
    assert right_snapshot is not None
    assert left_snapshot.base.content == (255, 0, 0)
    assert right_snapshot.base.content == (0, 0, 255)
    assert surface.content == (0, 0, 255)
    assert events == [
        "clear",
        "draw:background",
        "capture",
        "blit:screen_texture",
        "draw:later",
        "capture",
        "blit:screen_texture",
    ]


def test_first_screen_consumer_auto_captures_preceding_pixels() -> None:
    scene = Scene("automatic effect")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(
        ScreenTextureComponent(capture_id="screen", phase=RenderPhase.OPAQUE, width=2.0, height=2.0)
    )
    frame = extract_render_frame(scene)

    plan = RenderPlanBuilder.from_frame(frame, _context())
    captures = [operation for operation in plan.operations if isinstance(operation, CaptureScreenOp)]
    assert len(captures) == 1
    assert captures[0].automatic is True
    assert captures[0].request.capture_id == "screen"

    events: list[str] = []
    renderer, _pygame, surface = _renderer(events)
    renderer.render(frame)

    snapshot = renderer._screen_pipeline.snapshot("screen")
    assert snapshot is not None
    assert snapshot.base.content == (255, 0, 0)
    assert surface.subsurfaces == [(0, 0, 100, 100)]
    assert events == ["clear", "draw:background", "capture", "blit:screen_texture"]


def test_canvas_modulate_is_captured_once_and_screen_tint_stays_on_sample() -> None:
    scene = Scene("modulated effects")
    canvas = scene.create_entity("canvas", entity_id="canvas")
    canvas.add_component(CanvasModulateComponent((0.5, 0.5, 0.5, 0.5)))
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode=BackBufferCopyMode.VIEWPORT))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(
        ScreenTextureComponent(
            capture_id="screen",
            width=2.0,
            height=2.0,
            tint=Color(0.5, 0.25, 0.75, 0.8),
            opacity=0.5,
        )
    )

    events: list[str] = []
    renderer, pygame, surface = _renderer(events)
    renderer.render(extract_render_frame(scene))

    assert pygame.draw.rects[1][1] == (128, 0, 0, 128)
    snapshot = renderer._screen_pipeline.snapshot("screen")
    assert snapshot is not None
    assert snapshot.base.content == (128, 0, 0, 128)
    assert surface.fills == []
    assert snapshot.base.fills == []
    sampled_surface, _size = pygame.transform.smoothscales[-1]
    assert sampled_surface is not snapshot.base
    assert sampled_surface.fills == [((128, 64, 191, 102), 7)]
    assert events == [
        "clear",
        "draw:background",
        "capture",
        "blit:screen_texture",
    ]


def test_ordinary_extraction_matches_direct_renderer_draw_order_and_colors() -> None:
    scene = Scene("ordinary")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0)))
    later = scene.create_entity("later", entity_id="later")
    later.add_component(PrimitiveComponent(fill=Color(0.0, 0.0, 1.0)))
    extracted = extract_render_frame(scene)
    assert extracted.submissions == ()

    direct_events: list[str] = []
    direct_renderer, direct_pygame, _direct_surface = _renderer(direct_events)
    direct_renderer.render(RenderFrame(extracted.items))

    extracted_events: list[str] = []
    extracted_renderer, extracted_pygame, _extracted_surface = _renderer(extracted_events)
    extracted_renderer.render(extracted)

    direct_draws = [(color, rectangle) for _, color, rectangle, _ in direct_pygame.draw.rects]
    extracted_draws = [
        (color, rectangle) for _, color, rectangle, _ in extracted_pygame.draw.rects
    ]
    assert extracted_events == direct_events
    assert extracted_draws == direct_draws
