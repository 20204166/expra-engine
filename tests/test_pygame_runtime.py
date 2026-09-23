"""Tests for the injected Pygame runtime adapter."""

import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.runtime import project_runner
from expra_engine.runtime import (
    PygameRenderer,
    PygameRuntime,
    RenderContext,
    RenderContractFrame,
    Viewport,
)
from expra_engine.runtime.pygame_renderer import PygameRenderFrame
from expra_engine.runtime.pygame_screen_pipeline import PygameScreenSnapshot
from expra_engine.runtime.pygame_screen_pipeline import PygameScreenPipeline
from expra_engine.runtime.render_pipeline import RenderPlan, RenderPlanBuilder
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    BackBufferCopyRequest,
    RenderEffect,
    ScreenTextureComponent,
    ScreenTextureDrawRequest,
    ScreenTextureFilter,
)
from expra_engine.runtime.ui import Button, GameCanvas, LayoutSpec
from expra_engine.runtime.ui import Viewport as UIViewport
from expra_engine.runtime.visual_components import PrimitiveComponent


class _FakeSurface:
    pass


class _FakeClock:
    def __init__(self, milliseconds: list[int]) -> None:
        self.milliseconds = iter(milliseconds)
        self.limits: list[int] = []

    def tick(self, frame_rate: int) -> int:
        self.limits.append(frame_rate)
        return next(self.milliseconds)


class _FakeDisplay:
    def __init__(self) -> None:
        self.sizes: list[tuple[int, int]] = []
        self.flips = 0

    def set_mode(self, size: tuple[int, int]) -> _FakeSurface:
        self.sizes.append(size)
        return _FakeSurface()

    def flip(self) -> None:
        self.flips += 1


class _FakePygame:
    QUIT = 1
    KEYDOWN = 2
    KEYUP = 3
    MOUSEMOTION = 5
    MOUSEBUTTONDOWN = 6
    MOUSEBUTTONUP = 7

    def __init__(self, frames: list[list[Any]]) -> None:
        self.event = SimpleNamespace(get=lambda: frames.pop(0))
        self.display = _FakeDisplay()
        self.init_calls = 0
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1

    def init(self) -> None:
        self.init_calls += 1


class _FakeEngine:
    def __init__(self) -> None:
        self.dts: list[float] = []
        self.run_state = SimpleNamespace(value="play")
        self.stop_after_tick = False
        self.signals: list[object] = []

    def tick(self, dt: float) -> None:
        self.dts.append(dt)
        if self.stop_after_tick:
            self.run_state.value = "edit"

    def signal(self, event: object) -> None:
        self.signals.append(event)


class _ResizeProbeRenderer(PygameRenderer):
    def __init__(self, pygame_module: object) -> None:
        super().__init__(pygame_module, None)
        self.render_count = 0
        self.after_resize_captures: tuple[str, ...] | None = None

    def render(self, frame: object) -> None:
        self.render_count += 1
        if self.render_count == 1:
            self._screen_pipeline._captures["screen"] = PygameScreenSnapshot(
                (0, 0), (object(),)
            )
        elif self.render_count == 2:
            self.after_resize_captures = self._screen_pipeline.capture_ids
        super().render(frame)  # type: ignore[arg-type]


class _RecordingRenderer:
    capabilities = SimpleNamespace(resize=True)

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def start(self, context: RenderContext) -> None:
        self.calls.append(("start", context))

    def render(self, frame: object) -> None:
        self.calls.append(("render", frame))

    def resize(self, viewport: Viewport) -> None:
        self.calls.append(("resize", viewport))

    def stop(self) -> None:
        self.calls.append(("stop", None))


class _FailingStopRenderer(_RecordingRenderer):
    def stop(self) -> None:
        self.calls.append(("stop", None))
        raise RuntimeError("stop unavailable")


class TestPygameRuntime(unittest.TestCase):
    def test_runtime_updates_camera_following_before_render(self) -> None:
        from expra_engine.runtime import OrthographicCamera

        pygame = _FakePygame([[], [SimpleNamespace(type=_FakePygame.QUIT)]])
        camera = OrthographicCamera()
        camera.position_smoothing_enabled = False
        camera.target_position = (7.0, -3.0)
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=_RecordingRenderer(),
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
            camera=camera,
        )

        runtime.run()

        self.assertEqual(camera.position[:2], (7.0, -3.0))

    def test_runtime_rejects_invalid_camera_delta_without_silent_fallback(self) -> None:
        from expra_engine.runtime import OrthographicCamera

        camera = OrthographicCamera()
        with self.assertRaises(ValueError):
            camera.update(-1.0)

    def test_runtime_binds_camera_to_scene_entity_and_converts_input(self) -> None:
        from expra_engine.runtime import OrthographicCamera

        scene = Scene("Follow")
        target = scene.create_entity("Target", entity_id="target")
        target.add_component(TransformComponent(x=7.0, y=-3.0))
        engine = _FakeEngine()
        engine.active_scene = scene
        camera = OrthographicCamera(width=20.0, height=10.0)
        runtime = PygameRuntime(
            engine,
            pygame_module=_FakePygame([[], [SimpleNamespace(type=_FakePygame.QUIT)]]),
            clock=_FakeClock([16, 16]),
            surface_factory=lambda size: _FakeSurface(),
            camera=camera,
            camera_target_id="target",
        )

        runtime.run()

        self.assertEqual(camera.position[:2], (7.0, -3.0))
        self.assertEqual(runtime.screen_to_world((400.0, 300.0)), (7.0, -3.0))

    def test_runtime_applies_persisted_scene_camera_settings_once(self) -> None:
        from expra_engine.runtime import OrthographicCamera

        scene = Scene("Configured")
        scene.camera = {"position": [4.0, 5.0, 2.0], "zoom": 2.0, "rotation": 0.25}
        engine = _FakeEngine()
        engine.active_scene = scene
        camera = OrthographicCamera()
        runtime = PygameRuntime(
            engine,
            pygame_module=_FakePygame([[], [SimpleNamespace(type=_FakePygame.QUIT)]]),
            clock=_FakeClock([16, 16]),
            surface_factory=lambda size: _FakeSurface(),
            camera=camera,
        )

        runtime.run()

        self.assertEqual(camera.position, (4.0, 5.0, 2.0))
        self.assertEqual(camera.zoom, 2.0)
        self.assertEqual(camera.rotation, 0.25)

    def test_ui_owns_pointer_events_before_gameplay_input(self) -> None:
        pygame = _FakePygame(
            [
                [
                    SimpleNamespace(type=_FakePygame.MOUSEMOTION, pos=(10, 10)),
                    SimpleNamespace(type=_FakePygame.MOUSEBUTTONDOWN, pos=(10, 10), button=1),
                    SimpleNamespace(type=_FakePygame.MOUSEBUTTONUP, pos=(10, 10), button=1),
                ],
                [SimpleNamespace(type=_FakePygame.QUIT)],
            ]
        )
        canvas = GameCanvas()
        canvas.add(Button("play", layout=LayoutSpec(size=(100, 50))))
        canvas.layout(UIViewport(200, 100))
        engine = _FakeEngine()
        runtime = PygameRuntime(
            engine,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
            ui_root=canvas,
        )

        runtime.run()

        self.assertEqual(engine.signals, [])
    def test_runtime_stops_when_engine_returns_to_edit(self) -> None:
        pygame = _FakePygame([[], []])
        engine = _FakeEngine()
        engine.stop_after_tick = True
        runtime = PygameRuntime(
            engine,
            pygame_module=pygame,
            clock=_FakeClock([16]),
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()

        self.assertEqual(pygame.quit_calls, 1)

    def test_starts_renderer_renders_contract_frames_and_stops_in_order(self) -> None:
        pygame = _FakePygame([[], [SimpleNamespace(type=_FakePygame.QUIT)]])
        renderer = _RecordingRenderer()
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
            size=(320, 240),
        )

        runtime.run()

        self.assertEqual(
            [name for name, _ in renderer.calls], ["start", "render", "render", "stop"]
        )
        self.assertIsInstance(renderer.calls[0][1], RenderContext)
        self.assertEqual(renderer.calls[0][1].viewport, Viewport(0, 0, 320, 240))

    def test_frame_factory_supplies_backend_neutral_frame_payload_to_renderer(self) -> None:
        pygame = _FakePygame([[], [SimpleNamespace(type=_FakePygame.QUIT)]])
        renderer = _RecordingRenderer()
        payload = object()
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
            frame_factory=lambda engine, elapsed: RenderContractFrame(
                elapsed=elapsed, payload=payload
            ),
        )

        runtime.run()

        frames = [frame for name, frame in renderer.calls if name == "render"]
        self.assertEqual(len(frames), 2)
        self.assertIs(frames[0].payload, payload)
        self.assertNotIn("pygame", type(frames[0].payload).__module__.lower())

    def test_resize_preserves_the_active_camera(self) -> None:
        from expra_engine.runtime import OrthographicCamera

        pygame = _FakePygame(
            [[SimpleNamespace(type=4, size=(640, 480))], [SimpleNamespace(type=_FakePygame.QUIT)]]
        )
        pygame.VIDEORESIZE = 4
        renderer = _RecordingRenderer()
        camera = OrthographicCamera(position=(4, 5, 6), width=20, height=10, near=-3, far=7)
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
            camera=camera,
        )

        runtime.run()

        contexts = [value for name, value in renderer.calls if name == "start"]
        resize_context = runtime._context
        self.assertEqual(contexts[0].camera, camera)
        self.assertEqual(resize_context.camera, camera)

    def test_resize_event_updates_context_and_renderer(self) -> None:
        pygame = _FakePygame(
            [[SimpleNamespace(type=4, size=(640, 480))], [SimpleNamespace(type=_FakePygame.QUIT)]]
        )
        pygame.VIDEORESIZE = 4
        renderer = _RecordingRenderer()
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()

        self.assertIn(("resize", Viewport(0, 0, 640, 480)), renderer.calls)

    def test_resize_clears_renderer_screen_captures_before_next_frame(self) -> None:
        pygame = _FakePygame(
            [
                [],
                [SimpleNamespace(type=4, size=(640, 480))],
                [SimpleNamespace(type=_FakePygame.QUIT)],
            ]
        )
        pygame.VIDEORESIZE = 4
        renderer = _ResizeProbeRenderer(pygame)
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16, 16]),
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()

        self.assertEqual(renderer.after_resize_captures, ())

    def test_runtime_restart_clears_stale_renderer_screen_captures(self) -> None:
        pygame = _FakePygame([[SimpleNamespace(type=_FakePygame.QUIT)]])
        renderer = PygameRenderer(pygame, None)
        renderer._screen_pipeline._captures["screen"] = PygameScreenSnapshot(
            (0, 0), (object(),)
        )
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16, 16]),
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()
        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

        pygame.event = SimpleNamespace(
            get=lambda: [SimpleNamespace(type=_FakePygame.QUIT)]
        )
        renderer._screen_pipeline._captures["screen"] = PygameScreenSnapshot(
            (0, 0), (object(),)
        )
        runtime.run()

        self.assertEqual(renderer._screen_pipeline.capture_ids, ())

    def test_renderer_stops_and_pygame_quits_when_render_raises(self) -> None:
        pygame = _FakePygame([[]])
        renderer = _RecordingRenderer()

        def broken_render(frame: object) -> None:
            renderer.calls.append(("render", frame))
            raise RuntimeError("render unavailable")

        renderer.render = broken_render
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16]),
            surface_factory=pygame.display.set_mode,
        )

        with self.assertRaisesRegex(RuntimeError, "render unavailable"):
            runtime.run()

        self.assertEqual([name for name, _ in renderer.calls], ["start", "render", "stop"])
        self.assertEqual(pygame.quit_calls, 1)

    def test_pygame_quits_even_when_renderer_stop_raises(self) -> None:
        pygame = _FakePygame([[SimpleNamespace(type=_FakePygame.QUIT)]])
        renderer = _FailingStopRenderer()
        runtime = PygameRuntime(
            _FakeEngine(),
            renderer=renderer,
            pygame_module=pygame,
            clock=_FakeClock([16]),
            surface_factory=pygame.display.set_mode,
        )

        with self.assertRaisesRegex(RuntimeError, "stop unavailable"):
            runtime.run()

        self.assertEqual(pygame.quit_calls, 1)

    def test_exports_runtime_and_tracks_keyboard_state(self) -> None:
        pygame = _FakePygame(
            [
                [SimpleNamespace(type=_FakePygame.KEYDOWN, key=97)],
                [
                    SimpleNamespace(type=_FakePygame.KEYUP, key=97),
                    SimpleNamespace(type=_FakePygame.QUIT),
                ],
            ]
        )
        clock = _FakeClock([16, 20])
        engine = _FakeEngine()
        runtime = PygameRuntime(
            engine,
            pygame_module=pygame,
            clock=clock,
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()

        self.assertEqual(runtime.keys, frozenset())
        self.assertEqual(engine.dts, [0.016, 0.020])

    def test_quit_stops_loop_flips_frames_and_cleans_up_once(self) -> None:
        pygame = _FakePygame(
            [
                [],
                [SimpleNamespace(type=_FakePygame.QUIT)],
            ]
        )
        clock = _FakeClock([16, 16])
        engine = _FakeEngine()
        runtime = PygameRuntime(
            engine,
            pygame_module=pygame,
            clock=clock,
            surface_factory=pygame.display.set_mode,
            size=(320, 240),
            frame_rate=30,
        )

        runtime.run()

        self.assertEqual(pygame.display.sizes, [(320, 240)])
        self.assertEqual(pygame.display.flips, 2)
        self.assertEqual(clock.limits, [30, 30])
        self.assertEqual(pygame.quit_calls, 1)
        self.assertEqual(pygame.init_calls, 1)

    def test_explicit_stop_ends_after_current_frame(self) -> None:
        pygame = _FakePygame([[], []])
        clock = _FakeClock([16])
        engine = _FakeEngine()
        runtime = PygameRuntime(
            engine,
            pygame_module=pygame,
            clock=clock,
            surface_factory=pygame.display.set_mode,
            render_callback=lambda surface, current_engine: runtime.stop(),
        )

        runtime.run()

        self.assertEqual(engine.dts, [0.016])
        self.assertEqual(pygame.display.flips, 1)
        self.assertEqual(pygame.quit_calls, 1)

    def test_cleanup_runs_when_setup_or_render_raises(self) -> None:
        pygame = _FakePygame([])
        clock = _FakeClock([])

        def broken_surface_factory(size: tuple[int, int]) -> _FakeSurface:
            raise RuntimeError("display unavailable")

        runtime = PygameRuntime(
            _FakeEngine(),
            pygame_module=pygame,
            clock=clock,
            surface_factory=broken_surface_factory,
        )
        with self.assertRaisesRegex(RuntimeError, "display unavailable"):
            runtime.run()
        self.assertEqual(pygame.quit_calls, 1)

        pygame = _FakePygame([[]])

        def broken_render(surface: object, current_engine: object) -> None:
            raise RuntimeError("render unavailable")

        runtime = PygameRuntime(
            _FakeEngine(),
            pygame_module=pygame,
            clock=_FakeClock([16]),
            surface_factory=pygame.display.set_mode,
            render_callback=broken_render,
        )
        with self.assertRaisesRegex(RuntimeError, "render unavailable"):
            runtime.run()
        self.assertEqual(pygame.quit_calls, 1)

    def test_quit_in_an_event_batch_prevents_later_key_events(self) -> None:
        pygame = _FakePygame(
            [
                [
                    SimpleNamespace(type=_FakePygame.QUIT),
                    SimpleNamespace(type=_FakePygame.KEYDOWN, key=97),
                ]
            ]
        )
        runtime = PygameRuntime(
            _FakeEngine(),
            pygame_module=pygame,
            clock=_FakeClock([16]),
            surface_factory=pygame.display.set_mode,
        )

        runtime.run()

        self.assertEqual(runtime.keys, frozenset())


def test_project_runner_carries_effect_submissions_and_legacy_payload(
    monkeypatch: Any, tmp_path: Path
) -> None:
    project = Project.create("Effects", tmp_path / "effects")
    scene = Scene("effects")
    background = scene.create_entity("background", entity_id="background")
    background.add_component(PrimitiveComponent("rectangle"))
    capture = scene.create_entity("capture", entity_id="capture")
    capture.add_component(BackBufferCopyComponent(copy_mode=BackBufferCopyMode.VIEWPORT))
    consumer = scene.create_entity("consumer", entity_id="consumer")
    consumer.add_component(ScreenTextureComponent())
    project.save_scene(scene)

    captured: dict[str, Any] = {}

    class Renderer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class Runtime:
        def __init__(self, engine: Any, _renderer: Any, **kwargs: Any) -> None:
            self.engine = engine
            self.frame_factory = kwargs["frame_factory"]

        def run(self) -> None:
            captured["engine"] = self.engine
            captured["frame"] = self.frame_factory(self.engine, 0.25)
            captured["empty_frame"] = self.frame_factory(
                SimpleNamespace(
                    active_scene=None,
                    transform_interpolator=None,
                    interpolation_fraction=0.0,
                    animated_sprite_system=SimpleNamespace(players={}),
                ),
                0.5,
            )

    pygame = SimpleNamespace(image=SimpleNamespace(load=lambda stream: stream.read()))
    monkeypatch.setitem(sys.modules, "pygame", pygame)
    monkeypatch.setattr(project_runner, "PygameRenderer", Renderer)
    monkeypatch.setattr(project_runner, "PygameRuntime", Runtime)

    project_runner.run_project(project.path)

    frame = captured["frame"]
    assert [
        entry.request.entity_id
        for entry in frame.submissions
        if isinstance(entry, RenderEffect)
    ] == ["capture", "consumer"]
    assert frame.items[0].key == "background"
    assert isinstance(frame.payload, PygameRenderFrame)
    assert frame.payload.active_scene is captured["engine"].active_scene

    empty_frame = captured["empty_frame"]
    assert empty_frame.items == ()
    assert empty_frame.submissions == ()
    assert isinstance(empty_frame.payload, PygameRenderFrame)
    assert empty_frame.payload.active_scene is None


def test_runtime_package_exports_screen_texture_integration_types() -> None:
    import expra_engine.runtime as runtime_package

    expected = {
        "BackBufferCopyComponent": BackBufferCopyComponent,
        "BackBufferCopyMode": BackBufferCopyMode,
        "BackBufferCopyRequest": BackBufferCopyRequest,
        "RenderEffect": RenderEffect,
        "ScreenTextureComponent": ScreenTextureComponent,
        "ScreenTextureDrawRequest": ScreenTextureDrawRequest,
        "ScreenTextureFilter": ScreenTextureFilter,
        "RenderPlan": RenderPlan,
        "RenderPlanBuilder": RenderPlanBuilder,
        "PygameScreenPipeline": PygameScreenPipeline,
    }

    for name, expected_type in expected.items():
        assert name in runtime_package.__all__
        assert getattr(runtime_package, name) is expected_type


if __name__ == "__main__":
    unittest.main()
