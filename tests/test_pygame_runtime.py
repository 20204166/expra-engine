"""Tests for the injected Pygame runtime adapter."""

import unittest
from types import SimpleNamespace
from typing import Any

from expra_engine.runtime import PygameRuntime, RenderContext, RenderContractFrame, Viewport


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

    def tick(self, dt: float) -> None:
        self.dts.append(dt)
        if self.stop_after_tick:
            self.run_state.value = "edit"


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


if __name__ == "__main__":
    unittest.main()
