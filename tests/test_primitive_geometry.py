"""Polygon and line primitive geometry for the runtime renderer.

The 2.5D isometric renderer family draws arbitrary filled polygons (cube faces)
and lines (detail strokes). These tests lock in validation, serialization,
extraction, and headless Pygame rasterization so the geometry support does not
regress.
"""

from __future__ import annotations

import unittest

from expra_engine.core.scene import Scene
from expra_engine.runtime.pygame_renderer import PygameRenderer
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.rendering import (
    OrthographicCamera,
    PrimitiveDescriptor,
    RenderContext,
    RenderItem,
    Transform,
    Viewport,
)
from expra_engine.runtime.visual_components import PrimitiveComponent


def _render_scene(scene: Scene, size: tuple[int, int] = (101, 101)):
    import pygame

    surface = pygame.Surface(size)
    renderer = PygameRenderer(pygame, surface, clear_color=(0, 0, 0))
    renderer.start(
        RenderContext(Viewport(0, 0, size[0], size[1]), OrthographicCamera(width=10.0, height=10.0))
    )
    renderer.render(extract_render_frame(scene))
    return surface


class PrimitivePolygonValidationTests(unittest.TestCase):
    def test_polygon_requires_at_least_three_points(self) -> None:
        with self.assertRaises(ValueError):
            PrimitiveComponent(kind="polygon", points=((0.0, 0.0), (1.0, 1.0)))

    def test_polygon_rejects_malformed_point(self) -> None:
        with self.assertRaises(ValueError):
            PrimitiveComponent(kind="polygon", points=[(0.0, 0.0), (1.0,), (2.0, 2.0)])

    def test_polygon_rejects_non_finite_point(self) -> None:
        with self.assertRaises(ValueError):
            PrimitiveComponent(
                kind="polygon",
                points=[(0.0, 0.0), (float("inf"), 1.0), (2.0, 2.0)],
            )

    def test_polygon_round_trips_points(self) -> None:
        points = ((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0))
        component = PrimitiveComponent(kind="polygon", points=points, fill=(1.0, 0.0, 0.0, 1.0))
        restored = PrimitiveComponent.from_dict(component.to_dict())
        self.assertEqual(restored.kind, "polygon")
        self.assertEqual(restored.points, points)


class PrimitiveLineValidationTests(unittest.TestCase):
    def test_line_requires_exactly_two_points(self) -> None:
        with self.assertRaises(ValueError):
            PrimitiveComponent(kind="line", points=[(0.0, 0.0)])

    def test_line_rejects_non_positive_thickness(self) -> None:
        with self.assertRaises(ValueError):
            PrimitiveComponent(kind="line", points=[(0.0, 0.0), (1.0, 0.0)], thickness=0.0)

    def test_line_round_trips_points_and_thickness(self) -> None:
        component = PrimitiveComponent(
            kind="line", points=[(-3.0, 0.0), (3.0, 0.0)], fill=(1.0, 1.0, 1.0, 1.0), thickness=2.5
        )
        restored = PrimitiveComponent.from_dict(component.to_dict())
        self.assertEqual(restored.kind, "line")
        self.assertEqual(restored.points, ((-3.0, 0.0), (3.0, 0.0)))
        self.assertEqual(restored.thickness, 2.5)


class PrimitiveGeometryExtractionTests(unittest.TestCase):
    def test_polygon_extracts_points(self) -> None:
        scene = Scene("polygon")
        points = ((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0))
        scene.create_entity("diamond").add_component(
            PrimitiveComponent(kind="polygon", points=points)
        )
        frame = extract_render_frame(scene)
        self.assertEqual(len(frame.items), 1)
        self.assertEqual(frame.items[0].primitive.kind, "polygon")
        self.assertEqual(frame.items[0].primitive.points, tuple(points))

    def test_line_extracts_points_and_thickness(self) -> None:
        scene = Scene("line")
        scene.create_entity("stroke").add_component(
            PrimitiveComponent(kind="line", points=[(-3.0, 0.0), (3.0, 0.0)], thickness=2.5)
        )
        frame = extract_render_frame(scene)
        self.assertEqual(frame.items[0].primitive.kind, "line")
        self.assertEqual(frame.items[0].primitive.thickness, 2.5)


class PrimitiveGeometryRasterizationTests(unittest.TestCase):
    def test_polygon_visibility_uses_local_point_extents(self) -> None:
        item = RenderItem(
            "offset_polygon",
            PrimitiveDescriptor(
                "polygon",
                points=((-8.0, -1.0), (-6.0, -1.0), (-6.0, 1.0), (-8.0, 1.0)),
            ),
            Transform(position=(8.0, 0.0, 0.0)),
        )
        context = RenderContext(
            Viewport(0, 0, 100, 100), OrthographicCamera(width=10.0, height=10.0)
        )

        self.assertTrue(item.is_visible(context))

    def test_line_visibility_uses_local_point_extents(self) -> None:
        item = RenderItem(
            "offset_line",
            PrimitiveDescriptor("line", points=((-8.0, 0.0), (-6.0, 0.0)), thickness=0.5),
            Transform(position=(8.0, 0.0, 0.0)),
        )
        context = RenderContext(
            Viewport(0, 0, 100, 100), OrthographicCamera(width=10.0, height=10.0)
        )

        self.assertTrue(item.is_visible(context))

    def test_polygon_visibility_rejects_geometry_outside_viewport(self) -> None:
        item = RenderItem(
            "offscreen_polygon",
            PrimitiveDescriptor(
                "polygon",
                points=((1.0, -1.0), (3.0, -1.0), (3.0, 1.0), (1.0, 1.0)),
            ),
            Transform(position=(8.0, 0.0, 0.0)),
        )
        context = RenderContext(
            Viewport(0, 0, 100, 100), OrthographicCamera(width=10.0, height=10.0)
        )

        self.assertFalse(item.is_visible(context))

    def test_polygon_rasterizes_fill(self) -> None:
        scene = Scene("polygon")
        scene.create_entity("diamond").add_component(
            PrimitiveComponent(
                kind="polygon",
                points=((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0)),
                fill=(1.0, 0.0, 0.0, 1.0),
            )
        )
        surface = _render_scene(scene)
        center = surface.get_at((50, 50))
        self.assertGreater(center.r, 240)
        self.assertLess(center.g, 20)
        self.assertLess(center.b, 20)

    def test_polygon_rasterizes_outline(self) -> None:
        scene = Scene("polygon")
        scene.create_entity("diamond").add_component(
            PrimitiveComponent(
                kind="polygon",
                points=((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0)),
                fill=(1.0, 0.0, 0.0, 1.0),
                outline=(0.0, 1.0, 0.0, 1.0),
                outline_width=0.5,
            )
        )
        surface = _render_scene(scene)
        found_outline = False
        for x in range(20, 81):
            for y in range(20, 81):
                color = surface.get_at((x, y))
                if color.g > 200 and color.r < 60:
                    found_outline = True
                    break
            if found_outline:
                break
        self.assertTrue(found_outline)

    def test_line_rasterizes_stroke(self) -> None:
        scene = Scene("line")
        scene.create_entity("stroke").add_component(
            PrimitiveComponent(
                kind="line",
                points=[(-4.0, 0.0), (4.0, 0.0)],
                fill=(1.0, 1.0, 1.0, 1.0),
                thickness=1.0,
            )
        )
        surface = _render_scene(scene)
        center = surface.get_at((50, 50))
        self.assertGreater(center.r, 240)
        self.assertGreater(center.g, 240)
        self.assertGreater(center.b, 240)

    def test_isometric_cube_faces_render(self) -> None:
        scene = Scene("cube")
        top = ((-2.0, 0.0), (0.0, -1.0), (2.0, 0.0), (0.0, 1.0))
        scene.create_entity("top").add_component(
            PrimitiveComponent(kind="polygon", points=top, fill=(0.5, 0.8, 0.5, 1.0))
        )
        left = ((-2.0, 0.0), (0.0, 1.0), (0.0, 3.0), (-2.0, 2.0))
        scene.create_entity("left").add_component(
            PrimitiveComponent(kind="polygon", points=left, fill=(0.3, 0.5, 0.3, 1.0))
        )
        right = ((0.0, 1.0), (2.0, 0.0), (2.0, 2.0), (0.0, 3.0))
        scene.create_entity("right").add_component(
            PrimitiveComponent(kind="polygon", points=right, fill=(0.2, 0.35, 0.2, 1.0))
        )
        surface = _render_scene(scene)
        non_background = sum(
            1
            for x in range(0, 101, 2)
            for y in range(0, 101, 2)
            if surface.get_at((x, y))[:3] != (0, 0, 0)
        )
        self.assertGreater(non_background, 0)


if __name__ == "__main__":
    unittest.main()
