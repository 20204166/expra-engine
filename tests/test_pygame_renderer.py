"""Tests for the injected primitive Pygame renderer."""

import unittest
from types import SimpleNamespace

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.runtime import PygameRenderer, RenderFrame


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


if __name__ == "__main__":
    unittest.main()
