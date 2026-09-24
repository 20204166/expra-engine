"""Tests for editor-side render target resolution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast

from expra_engine.coordinators.ui_coordinator import RenderIntent, UICoordinator
from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.editor.contributions import RenderTargetRegistry
from expra_engine.runtime.canvas_effects import CanvasModulateComponent
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    ScreenTextureComponent,
)
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.visual_components import (
    PrimitiveComponent,
    SpriteComponent,
    TextComponent,
)
from expra_engine.ui.editor_window import EditorWindow
from expra_engine.ui.viewport import ViewportCamera, build_editor_render_target


class RenderTargetRegistryTests(unittest.TestCase):
    def test_registered_target_receives_intent(self) -> None:
        applied: list[Any] = []
        targets = RenderTargetRegistry()
        targets.register("panel", applied.append)

        targets.callback_for("panel")(RenderIntent(target="panel", payload="value"))

        self.assertEqual(applied[0].payload, "value")

    def test_unknown_target_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            RenderTargetRegistry().callback_for("missing")

    def test_replacement_invalidates_pending_old_callback(self) -> None:
        old: list[Any] = []
        new: list[Any] = []
        targets = RenderTargetRegistry()
        targets.register("panel", old.append)
        old_callback = targets.callback_for("panel")
        coordinator = UICoordinator()
        coordinator.begin_batch()
        coordinator.request(RenderIntent(target="panel"), old_callback)
        targets.register("panel", new.append, replace=True)
        coordinator.end_batch()

        self.assertEqual(old, [])
        self.assertEqual(new, [])

    def test_callback_failure_reaches_ui_coordinator_isolation(self) -> None:
        def failing(_intent: RenderIntent) -> None:
            raise RuntimeError("broken panel")

        targets = RenderTargetRegistry()
        targets.register("panel", failing)
        coordinator = UICoordinator()

        coordinator.request(RenderIntent(target="panel"), targets.callback_for("panel"))

        self.assertEqual(coordinator.render_failures, 1)


class EditorRenderTargetTests(unittest.TestCase):
    def test_editor_viewport_routes_runtime_interpolation_only_during_play(self) -> None:
        class ViewportSink:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def render(self, scene: Scene, selected_id: str | None, **kwargs: Any) -> None:
                self.calls.append({"scene": scene, "selected_id": selected_id, **kwargs})

        interpolator = object()
        sink = ViewportSink()
        window = cast(Any, EditorWindow.__new__(EditorWindow))
        window._viewport = sink
        window._engine = SimpleNamespace(
            run_state=EngineRunState.EDIT,
            transform_interpolator=interpolator,
            interpolation_fraction=0.5,
            animated_sprite_system=SimpleNamespace(players={}),
        )
        scene = Scene("routing")

        for state, overlays, expected_interpolator in (
            (EngineRunState.EDIT, True, None),
            (EngineRunState.PLAY, False, interpolator),
            (EngineRunState.PAUSED, False, interpolator),
        ):
            window._engine.run_state = state
            window._render_viewport(RenderIntent(target="viewport", payload=(scene, None)))
            call = sink.calls[-1]
            self.assertEqual(call["editor_overlays"], overlays)
            self.assertIs(call["interpolator"], expected_interpolator)
            self.assertEqual(call["interpolation_fraction"], 0.5 if expected_interpolator else 0.0)

    def test_target_uses_extracted_visuals_and_preserves_colors_and_layer_order(self) -> None:
        scene = Scene("preview")
        primitive = scene.create_entity("primitive", entity_id="primitive", layer=2)
        primitive.add_component(TransformComponent(x=-2.0, y=1.0))
        primitive.add_component(PrimitiveComponent(fill=Color(1.0, 0.0, 0.0), layer=1))
        sprite = scene.create_entity("sprite", entity_id="sprite", layer=0)
        sprite.add_component(SpriteComponent("ship", tint=Color(0.0, 1.0, 0.0), layer=2))
        text = scene.create_entity("text", entity_id="text", layer=0)
        text.add_component(TextComponent("Hello", color=Color(0.0, 0.0, 1.0), layer=3))

        target = build_editor_render_target(scene, viewport=(200, 100))

        self.assertEqual([item.key for item in target.items], ["sprite", "primitive", "text"])
        self.assertEqual(target.items[1].material.color, Color(1.0, 0.0, 0.0))
        self.assertEqual(target.items[2].text.text, "Hello")  # type: ignore[union-attr]

    def test_target_reuses_frame_canvas_modulation(self) -> None:
        scene = Scene("preview")
        entity = scene.create_entity("visual")
        entity.add_component(PrimitiveComponent(fill=Color(1.0, 0.5, 0.25)))
        entity.add_component(CanvasModulateComponent((0.5, 0.4, 0.3, 1.0)))

        target = build_editor_render_target(scene, viewport=(200, 100))

        self.assertEqual(target.frame.modulation, Color(0.5, 0.4, 0.3, 1.0))

    def test_target_uses_scene_camera_settings_for_large_worlds(self) -> None:
        scene = Scene("wide", camera={"position": [0.0, 0.0], "width": 100.0})
        paddle = scene.create_entity("paddle", entity_id="paddle")
        paddle.add_component(TransformComponent(x=45.0))
        paddle.add_component(PrimitiveComponent(width=2.0, height=12.0))

        target = build_editor_render_target(scene, viewport=(400, 300))

        self.assertEqual([item.key for item in target.items], ["paddle"])

    def test_play_camera_ignores_live_authoring_pan_when_camera_is_none(self) -> None:
        """Regression: Space Pong Edit/Play camera parity bug hunt.

        Passing camera=None (what ViewportPanel.render now does whenever
        editor_overlays is False, i.e. Play/Paused) must derive the preview
        camera purely from scene.camera, completely independent of any pan
        applied to a live authoring ViewportCamera. Before the fix,
        build_editor_render_target always overrode the preview camera's
        position with the live editor camera's position, so panning the Edit
        viewport before pressing Play silently changed -- or hid entirely --
        the game's framing.
        """
        scene = Scene("space-pong-like", camera={"position": [0.0, 0.0], "width": 100.0})
        ball = scene.create_entity("ball", entity_id="ball")
        ball.add_component(TransformComponent(x=0.0, y=0.0))
        ball.add_component(PrimitiveComponent(kind="circle", width=2.0, height=2.0, radius=1.0))

        # Pan the authoring camera far enough that a ball sitting at scene
        # origin would fall completely outside a width=100 frame centered
        # there -- if Play leaked this pan, the ball would be clipped.
        panned_authoring_camera = ViewportCamera((400, 300))
        panned_authoring_camera.pan(500.0, 500.0)

        edit_target = build_editor_render_target(
            scene, viewport=(400, 300), camera=panned_authoring_camera
        )
        play_target = build_editor_render_target(scene, viewport=(400, 300), camera=None)

        self.assertEqual(edit_target.items, (), "panned Edit camera should clip the origin ball")
        self.assertEqual(
            [item.key for item in play_target.items],
            ["ball"],
            "Play must frame the ball from scene.camera's saved (0, 0), ignoring the pan",
        )

    def test_play_camera_is_deterministic_across_repeated_play_stop_play(self) -> None:
        """Three consecutive Play sessions of the same scene must project
        identically -- the acceptance criterion from the camera parity bug
        hunt's Play -> Stop -> Play repeatability test."""
        scene = Scene("repeatable", camera={"position": [1.0, -2.0], "width": 80.0})
        arena = scene.create_entity("arena", entity_id="arena")
        arena.add_component(TransformComponent(x=0.0, y=0.0))
        arena.add_component(PrimitiveComponent(kind="rectangle", width=60.0, height=60.0))

        # Simulate a live authoring camera that drifts between Play sessions
        # (e.g. the user panned/zoomed the Edit viewport between runs) --
        # camera=None during Play must be immune to this drift entirely.
        drifting_camera = ViewportCamera((400, 300))

        keys_per_run = []
        positions_per_run = []
        for pan_amount in (0.0, 250.0, -400.0):
            drifting_camera.pan(pan_amount, pan_amount / 2.0)
            play_target = build_editor_render_target(scene, viewport=(400, 300), camera=None)
            keys_per_run.append([item.key for item in play_target.items])
            positions_per_run.append([item.world_transform.position for item in play_target.items])

        self.assertEqual(keys_per_run[0], ["arena"])
        self.assertEqual(keys_per_run[0], keys_per_run[1])
        self.assertEqual(keys_per_run[1], keys_per_run[2])
        self.assertEqual(positions_per_run[0], positions_per_run[1])
        self.assertEqual(positions_per_run[1], positions_per_run[2])

    def test_target_clips_offscreen_items_and_clears_removed_selection(self) -> None:
        scene = Scene("preview")
        entity = scene.create_entity("visible", entity_id="visible")
        entity.add_component(TransformComponent(x=100.0))
        entity.add_component(PrimitiveComponent())

        target = build_editor_render_target(scene, viewport=(200, 100), selected_id="removed")

        self.assertEqual(target.items, ())
        self.assertIsNone(target.selected_id)

    def test_target_exposes_collider_outlines_without_mutating_scene(self) -> None:
        scene = Scene("preview")
        entity = scene.create_entity("body", entity_id="body")
        entity.add_component(TransformComponent(x=2.0, y=-1.0))
        collider = ColliderComponent(width=4.0, height=2.0)
        entity.add_component(collider)

        target = build_editor_render_target(
            scene, viewport=(200, 100), selected_id=entity.entity_id
        )

        self.assertEqual(target.selected_id, "body")
        self.assertEqual(target.colliders[0].entity_id, "body")
        self.assertEqual(target.colliders[0].outline, collider.editor_outline)
        self.assertEqual(entity.get_component(TransformComponent).x, 2.0)  # type: ignore[union-attr]

    def test_target_skips_malformed_visuals_without_losing_valid_items(self) -> None:
        scene = Scene("preview")
        malformed = scene.create_entity("bad", entity_id="bad")
        malformed.add_component(PrimitiveComponent(kind="unknown"))
        valid = scene.create_entity("good", entity_id="good")
        valid.add_component(PrimitiveComponent(fill=Color(0.2, 0.3, 0.4)))

        target = build_editor_render_target(scene, viewport=(200, 100))

        self.assertEqual([item.key for item in target.items], ["good"])

    def test_target_reports_screen_effects_without_fake_pixels(self) -> None:
        scene = Scene("effects")
        background = scene.create_entity("background", entity_id="background")
        background.add_component(PrimitiveComponent("rectangle"))
        capture = scene.create_entity("capture", entity_id="capture")
        capture.add_component(BackBufferCopyComponent(copy_mode="viewport"))
        consumer = scene.create_entity("consumer", entity_id="consumer")
        consumer.add_component(ScreenTextureComponent())

        target = build_editor_render_target(scene, viewport=(200, 100))

        self.assertEqual([item.key for item in target.items], ["background"])
        self.assertEqual(target.unsupported_effects, ("capture", "consumer"))

    def test_target_uses_runtime_interpolation_when_supplied(self) -> None:
        scene = Scene("runtime preview")
        entity = scene.create_entity("moving", entity_id="moving")
        transform = TransformComponent()
        entity.add_component(transform)
        entity.add_component(PrimitiveComponent())
        interpolator = TransformInterpolator()
        interpolator.capture_scene(scene)

        transform.x = 10.0
        interpolator.capture_scene(scene)
        target = build_editor_render_target(
            scene,
            viewport=(200, 100),
            interpolator=interpolator,
            interpolation_fraction=0.5,
        )

        self.assertEqual(target.items[0].world_transform.position[0], 5.0)


class ViewportCameraTests(unittest.TestCase):
    def test_pan_zoom_frame_and_resize_keep_camera_bounded(self) -> None:
        camera = ViewportCamera((200, 100))
        camera.pan(3.0, -2.0)
        camera.zoom(100.0)
        camera.resize((400, 200))

        # zoom_level is the canonical zoom state; _camera.zoom is always 1.0
        # in the new BASE_PPU model (zoom encoded in target_width).
        self.assertGreater(camera.zoom_level, 0.0)
        self.assertGreater(camera._camera.pixel_ratio, 0.0)
        camera.frame_scene(((10.0, 5.0), (-2.0, -3.0)))
        self.assertEqual(camera.position, (4.0, 1.0))

    def test_zoom_clamps_at_both_edges_using_camera_zoom(self) -> None:
        from expra_engine.ui.viewport import _MAX_ZOOM, _MIN_ZOOM

        camera = ViewportCamera((200, 100))

        camera.zoom(-100.0)
        self.assertAlmostEqual(camera.zoom_level, _MIN_ZOOM)
        # Zoom in enough to guarantee we hit the upper clamp
        camera.zoom((_MAX_ZOOM / _MIN_ZOOM - 1) * 100.0 * 2)
        self.assertAlmostEqual(camera.zoom_level, _MAX_ZOOM)
        # pixel_ratio must remain finite and positive at both extremes
        self.assertGreater(camera._camera.pixel_ratio, 0.0)

    def test_resize_preserves_camera_zoom_state(self) -> None:
        camera = ViewportCamera((200, 100))
        camera.zoom(100.0)  # zoom_level becomes 2.0
        zoom_before = camera.zoom_level
        ppu_before = camera._camera.pixel_ratio
        camera.resize((400, 200))

        # zoom_level and pixel_ratio must be unchanged; only visible area grows.
        self.assertAlmostEqual(camera.zoom_level, zoom_before)
        self.assertAlmostEqual(camera._camera.pixel_ratio, ppu_before)

    def test_editor_camera_rotation_and_inverse_projection(self) -> None:
        camera = ViewportCamera((200, 100))
        camera.rotate(90.0)

        world = camera.unproject(camera.project((1.0, 0.0)))

        self.assertAlmostEqual(world[0], 1.0)
        self.assertAlmostEqual(world[1], 0.0)

    def test_editor_camera_state_applies_and_reset_clears_controls(self) -> None:
        camera = ViewportCamera((200, 100))
        camera.apply_dict({"position": [4.0, 5.0], "zoom": 2.0, "rotation": 0.5})
        camera.reset_view()

        self.assertEqual(camera.position, (0.0, 0.0))
        self.assertEqual(camera.zoom_level, 1.0)
        self.assertEqual(camera._camera.rotation, 0.0)

    def test_frame_selected_ignores_missing_entity(self) -> None:
        camera = ViewportCamera((200, 100))

        self.assertFalse(camera.frame_selected(None))


if __name__ == "__main__":
    unittest.main()
