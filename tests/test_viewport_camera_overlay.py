"""Tests for the editor-only scene-camera visualization overlay."""

from __future__ import annotations

import unittest
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.ui.viewport_camera_overlay import draw_camera_overlay


class _FakeCanvas:
    """Records shape-drawing calls without needing a real Tk widget."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_polygon(self, *args: Any, **kwargs: Any) -> int:
        self.calls.append("polygon")
        return len(self.calls)

    def create_rectangle(self, *args: Any, **kwargs: Any) -> int:
        self.calls.append("rectangle")
        return len(self.calls)

    def create_line(self, *args: Any, **kwargs: Any) -> int:
        self.calls.append("line")
        return len(self.calls)


class _IdentityCamera:
    """Editor camera stub: world coordinates pass through unchanged."""

    def project(self, point: tuple[float, float]) -> tuple[float, float]:
        return point


class DrawCameraOverlayTests(unittest.TestCase):
    def test_no_scene_camera_draws_nothing(self) -> None:
        scene = Scene("test")  # no camera configured -- scene.camera is an empty dict
        canvas = _FakeCanvas()

        draw_camera_overlay(canvas, scene, _IdentityCamera(), "f", "l", "t")

        self.assertEqual(canvas.calls, [])

    def test_configured_camera_draws_the_frame_polygon(self) -> None:
        scene = Scene("test")
        scene.camera = {"position": [1.0, 2.0], "width": 10.0}
        canvas = _FakeCanvas()

        draw_camera_overlay(canvas, scene, _IdentityCamera(), "f", "l", "t")

        self.assertIn("polygon", canvas.calls)

    def test_limit_enabled_draws_an_additional_rectangle(self) -> None:
        scene = Scene("test")
        scene.camera = {
            "position": [0.0, 0.0],
            "width": 10.0,
            "limit_enabled": True,
            "limits": [-50.0, -30.0, 50.0, 30.0],
        }
        canvas = _FakeCanvas()

        draw_camera_overlay(canvas, scene, _IdentityCamera(), "f", "l", "t")

        self.assertEqual(canvas.calls, ["polygon", "rectangle"])

    def test_follow_target_draws_a_line_to_the_target_entity(self) -> None:
        scene = Scene("test")
        target = scene.create_entity("Player")
        target.add_component(TransformComponent(x=3.0, y=4.0))
        scene.camera = {"position": [0.0, 0.0], "width": 10.0, "target_entity_id": target.entity_id}
        canvas = _FakeCanvas()

        draw_camera_overlay(canvas, scene, _IdentityCamera(), "f", "l", "t")

        self.assertEqual(canvas.calls, ["polygon", "line"])

    def test_missing_follow_target_entity_does_not_crash(self) -> None:
        scene = Scene("test")
        scene.camera = {"position": [0.0, 0.0], "width": 10.0, "target_entity_id": "gone"}
        canvas = _FakeCanvas()

        draw_camera_overlay(canvas, scene, _IdentityCamera(), "f", "l", "t")

        self.assertEqual(canvas.calls, ["polygon"])


if __name__ == "__main__":
    unittest.main()
