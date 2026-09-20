"""Tests for the injected primitive Pygame renderer."""

import unittest
from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime import (
    OrthographicCamera,
    PrimitiveDescriptor,
    PygameRenderer,
    PygameRenderFrame,
    RenderContext,
    RenderContractFrame,
    RenderFrame,
    RenderItem,
    RenderPhase,
    Transform,
    Viewport,
)


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

    def rect(self, surface: object, color: object, rectangle: object) -> None:
        self.rects.append((surface, color, rectangle))

    def circle(self, surface: object, color: object, center: object, radius: object) -> None:
        self.circles.append((surface, color, center, radius))

    def line(self, surface: object, color: object, start: object, end: object) -> None:
        self.lines.append((surface, color, start, end))


class _FakeFont:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def render(self, text: str, antialias: bool, color: object) -> object:
        self.texts.append(text)
        return (text, antialias, color)


class _FakePygame:
    def __init__(self, font: _FakeFont) -> None:
        self.draw = _FakeDraw()
        self.font = SimpleNamespace(Font=lambda name, size: font)


class TestPygameRenderer(unittest.TestCase):
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
