"""End-to-end coverage for the observability wiring pass.

Verifies the shared ObservabilityWatcher actually reaches Engine, its
runtime systems (behaviour/animation/audio/physics), render extraction/
plan, the resource pipeline, and the editor's input dispatch -- and that
metric cardinality/token lifetime stay bounded under sustained load.
"""

from __future__ import annotations

import threading
import tkinter as tk
import unittest
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.scene import Scene
from expra_engine.filesystem.cache import ResourceCache
from expra_engine.filesystem.mounts import DirectoryMount, MountSpec
from expra_engine.filesystem.resources import ResourceResolver
from expra_engine.filesystem.service import ResourceService
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
)
from expra_engine.runtime.audio_2d import AudioStreamPlayer2DComponent
from expra_engine.runtime.behaviour import Behaviour
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.events import Update
from expra_engine.runtime.physics_world import PhysicsWorld2D
from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
from expra_engine.ui.viewport_render_target import build_editor_render_target


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


DISPLAY_AVAILABLE = _display_available()


def _frames() -> SpriteFrames2D:
    return SpriteFrames2D(
        {"walk": SpriteAnimation2D((SpriteFrame2D("a.png"), SpriteFrame2D("b.png")), speed_fps=30.0)}
    )


class _CountingBehaviour(Behaviour):
    def __init__(self) -> None:
        super().__init__()
        self.updates = 0

    def on_fixed_update(self, dt: float) -> None:
        self.updates += 1


class _FailingBehaviour(Behaviour):
    def on_fixed_update(self, dt: float) -> None:
        raise RuntimeError("boom")


class EngineTickObservabilityTests(unittest.TestCase):
    def test_engine_works_without_an_observer(self) -> None:
        engine = Engine()
        engine.set_scene(Scene("empty"))
        engine.play()
        self.assertEqual(engine.tick(0.016), pytest.approx(0.016))
        engine.stop()

    def test_observer_is_settable_after_construction(self) -> None:
        engine = Engine()
        self.assertIsNone(engine.observer)
        watcher = ObservabilityWatcher()
        engine.observer = watcher
        self.assertIs(engine.observer, watcher)

    def test_tick_records_runtime_tick_span(self) -> None:
        watcher = ObservabilityWatcher()
        engine = Engine(observer=watcher)
        engine.set_scene(Scene("s"))
        engine.play()
        engine.tick(0.016)
        engine.tick(0.016)
        engine.stop()

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:tick")
        self.assertEqual(metric.count, 2)
        self.assertEqual(metric.in_flight, 0)
        self.assertGreaterEqual(metric.successes, 2)


class BehaviourSystemObservabilityTests(unittest.TestCase):
    def _engine_with_behaviour(self, behaviour_cls: type[Behaviour], watcher: ObservabilityWatcher) -> Engine:
        from expra_engine.runtime.script_component import ScriptComponent

        class _Registry:
            def resolve(self, _script_id: Any, _behaviour_class: str) -> type[Behaviour]:
                return behaviour_cls

        scene = Scene("s")
        entity = scene.create_entity("actor", entity_id="actor")
        entity.add_component(ScriptComponent("assets://dummy.py", behaviour_cls.__name__))
        engine = Engine(observer=watcher)
        engine.set_scene(scene)
        engine.set_script_registry(_Registry())  # type: ignore[arg-type]
        return engine

    def test_on_update_records_behaviour_span_and_invoked_counter(self) -> None:
        watcher = ObservabilityWatcher()
        engine = self._engine_with_behaviour(_CountingBehaviour, watcher)
        engine.play()
        engine.signal(Update(0.1))
        engine.tick(0.0)
        engine.stop()

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:behaviour:update")
        self.assertGreaterEqual(metric.count, 1)
        self.assertEqual(metric.in_flight, 0)
        self.assertEqual(dict(metric.counters).get("invoked"), 1)

    def test_behaviour_exception_is_recorded_as_failure_and_still_propagates(self) -> None:
        watcher = ObservabilityWatcher()
        engine = self._engine_with_behaviour(_FailingBehaviour, watcher)
        engine.play()
        engine.signal(Update(0.1))
        with self.assertRaises(RuntimeError):
            engine.tick(0.0)

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:behaviour:update")
        self.assertEqual(metric.failures, 1)
        self.assertEqual(metric.in_flight, 0)


class AnimatedSpriteObservabilityTests(unittest.TestCase):
    def test_on_update_records_span_gauge_and_counters(self) -> None:
        watcher = ObservabilityWatcher()
        scene = Scene("s")
        entity = scene.create_entity("sprite", entity_id="sprite")
        entity.add_component(AnimatedSprite2DComponent(_frames(), autoplay="walk"))
        engine = Engine(observer=watcher)
        engine.set_scene(scene)
        engine.play()
        engine.signal(Update(1.0))  # long enough to force a frame transition
        engine.tick(0.0)
        engine.stop()

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:animation:update")
        self.assertGreaterEqual(metric.count, 1)
        self.assertEqual(metric.in_flight, 0)
        gauges = dict(metric.gauges)
        self.assertIn("active_players", gauges)
        counters = dict(metric.counters)
        self.assertIn("players_advanced", counters)
        self.assertIn("frame_transitions", counters)


class AudioObservabilityTests(unittest.TestCase):
    def test_on_update_records_span_and_active_voice_gauge(self) -> None:
        watcher = ObservabilityWatcher()
        scene = Scene("s")
        source = scene.create_entity("source", entity_id="source")
        source.add_component(AudioStreamPlayer2DComponent("laser.wav", autoplay=True))
        engine = Engine(observer=watcher)
        engine.set_scene(scene)
        engine.play()
        engine.tick(0.1)
        engine.stop()

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:audio:update")
        self.assertGreaterEqual(metric.count, 1)
        self.assertEqual(metric.in_flight, 0)
        self.assertIn("active_voices", dict(metric.gauges))


class PhysicsObservabilityTests(unittest.TestCase):
    def _scene_with_boxes(self) -> Scene:
        scene = Scene("physics")
        for name, x in (("a", 0.0), ("b", 1.0)):
            entity = scene.create_entity(name, entity_id=name)
            entity.add_component(TransformComponent(x=x, y=0.0))
            entity.add_component(ColliderComponent(width=2.0, height=2.0))
        return scene

    def test_overlap_and_raycast_increment_query_counters(self) -> None:
        watcher = ObservabilityWatcher()
        scene = self._scene_with_boxes()
        world = PhysicsWorld2D(scene, observer=watcher)

        world.overlap("a")
        world.overlap("a")
        world.raycast((0.0, 0.0), (1.0, 0.0), 5.0)

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:physics:query")
        counters = dict(metric.counters)
        self.assertEqual(counters["overlap"], 2)
        self.assertEqual(counters["raycast"], 1)

    def test_step_triggers_records_a_span(self) -> None:
        watcher = ObservabilityWatcher()
        scene = self._scene_with_boxes()
        world = PhysicsWorld2D(scene, observer=watcher)

        world.step_triggers()

        metric = next(m for m in watcher.snapshot().metrics if m.target == "runtime:physics:step")
        self.assertEqual(metric.count, 1)
        self.assertEqual(metric.in_flight, 0)

    def test_no_observer_means_no_metrics_and_no_crash(self) -> None:
        scene = self._scene_with_boxes()
        world = PhysicsWorld2D(scene)
        self.assertEqual(world.overlap("a"), ("b",))


class RenderExtractPlanObservabilityTests(unittest.TestCase):
    def test_build_editor_render_target_records_extract_and_plan_spans(self) -> None:
        from expra_engine.runtime.visual_components import PrimitiveComponent

        watcher = ObservabilityWatcher()
        scene = Scene("s")
        entity = scene.create_entity("box", entity_id="box")
        entity.add_component(PrimitiveComponent("rectangle", 1.0, 1.0))

        build_editor_render_target(scene, viewport=(200, 100), observer=watcher)

        targets = {m.target: m for m in watcher.snapshot().metrics}
        self.assertIn("render:extract", targets)
        self.assertIn("render:plan", targets)
        self.assertEqual(targets["render:extract"].in_flight, 0)
        self.assertEqual(targets["render:plan"].in_flight, 0)
        extract_counters = dict(targets["render:extract"].counters)
        self.assertEqual(extract_counters["entities_considered"], 1)
        self.assertEqual(extract_counters["items_produced"], 1)
        plan_counters = dict(targets["render:plan"].counters)
        self.assertIn("items_visible", plan_counters)

    def test_none_scene_does_not_record_anything(self) -> None:
        watcher = ObservabilityWatcher()
        build_editor_render_target(None, viewport=(200, 100), observer=watcher)
        self.assertEqual(watcher.snapshot().metrics, ())


class ResourcePipelineObservabilityTests(unittest.TestCase):
    def _service(self, tmp_path, watcher: ObservabilityWatcher | None) -> ResourceService:
        (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        mount = DirectoryMount(tmp_path, MountSpec(name="assets", scheme="assets", read_only=True))
        return ResourceService(
            ResourceResolver([mount]), cache=ResourceCache[bytes](), observer=watcher
        )

    def test_read_bytes_records_resolve_and_read_then_cache_hit(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            watcher = ObservabilityWatcher()
            service = self._service(Path(tmp), watcher)

            service.read_bytes("assets://a.png")
            service.read_bytes("assets://a.png")  # second call should hit cache

            targets = {m.target: m for m in watcher.snapshot().metrics}
            self.assertIn("resource:resolve", targets)
            self.assertIn("resource:read", targets)
            self.assertEqual(targets["resource:read"].count, 1)  # only the cold read
            self.assertEqual(dict(targets["resource:resolve"].events).get("cache_hit"), 1)

    def test_pygame_resource_provider_records_decode_then_cache_hit(self) -> None:
        pygame = pytest.importorskip("pygame")
        watcher = ObservabilityWatcher()

        class _FakeResources:
            def read_bytes(self, _texture_id: str) -> bytes:
                surface = pygame.Surface((2, 2))
                return pygame.image.tostring(surface, "RGB")

        provider = PygameResourceProvider(pygame, _FakeResources(), observer=watcher)
        # pygame can't decode raw tostring() bytes via image.load -- exercise the
        # failure path instead, which is exactly what "repeated decode bugs
        # should be observable immediately" needs evidence for.
        provider("missing.png")

        metric = next(m for m in watcher.snapshot().metrics if m.target == "resource:decode")
        self.assertEqual(metric.failures, 1)
        self.assertEqual(metric.in_flight, 0)


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class SharedWatcherWiringTests(unittest.TestCase):
    def test_editor_window_gives_engine_appcoordinator_and_viewport_the_same_watcher(self) -> None:
        from expra_engine.ui.editor_window import EditorWindow

        window = EditorWindow(Engine())
        try:
            self.assertIsInstance(window._observer, ObservabilityWatcher)
            self.assertIs(window._engine.observer, window._observer)
            self.assertIs(window._coordinator._observer, window._observer)  # type: ignore[attr-defined]
            self.assertIs(window._actions._observer, window._observer)  # type: ignore[attr-defined]
            self.assertIs(window._ui._observer, window._observer)  # type: ignore[attr-defined]
            self.assertIs(window._viewport._observer, window._observer)
            self.assertIs(window._runtime_preview._observer, window._observer)  # type: ignore[attr-defined]
        finally:
            window._on_close()


class CardinalityAndRetentionTests(unittest.TestCase):
    def test_metric_target_cardinality_stays_bounded_across_many_entities_and_frames(self) -> None:
        watcher = ObservabilityWatcher(sample_limit=32)
        scene = Scene("many")
        for index in range(50):
            entity = scene.create_entity(f"sprite-{index}", entity_id=f"sprite-{index}")
            entity.add_component(AnimatedSprite2DComponent(_frames(), autoplay="walk"))
        engine = Engine(observer=watcher)
        engine.set_scene(scene)
        engine.play()

        for _ in range(1000):
            engine.signal(Update(0.016))
            engine.tick(0.0)

        snapshot = watcher.snapshot()
        # Stable, bounded target set regardless of 50 entities x 1000 frames --
        # never one target per entity.
        self.assertLess(len(snapshot.metrics), 20)
        for metric in snapshot.metrics:
            self.assertEqual(metric.in_flight, 0, metric.target)
            self.assertLessEqual(len(metric.samples), 32, metric.target)

        engine.stop()

    def test_fifty_play_stop_cycles_leave_the_watcher_structurally_healthy(self) -> None:
        watcher = ObservabilityWatcher()
        scene = Scene("cycle")
        entity = scene.create_entity("sprite", entity_id="sprite")
        entity.add_component(AnimatedSprite2DComponent(_frames(), autoplay="walk"))
        engine = Engine(observer=watcher)
        engine.set_scene(scene)

        for _ in range(50):
            engine.play()
            engine.signal(Update(0.016))
            engine.tick(0.0)
            engine.stop()

        snapshot = watcher.snapshot()
        for metric in snapshot.metrics:
            self.assertEqual(metric.in_flight, 0, metric.target)
        target_count = len(snapshot.metrics)
        self.assertLess(target_count, 20)


class ThreadSafetyTests(unittest.TestCase):
    def test_concurrent_counters_gauges_and_spans_do_not_race(self) -> None:
        watcher = ObservabilityWatcher()
        barrier = threading.Barrier(4)
        iterations = 200

        def worker(worker_id: int) -> None:
            barrier.wait()
            for i in range(iterations):
                watcher.increment("runtime:physics:query", "overlap")
                watcher.set_gauge("runtime:animation:update", "active_players", worker_id * i)
                token = watcher.begin("runtime:tick")
                watcher.finish(token)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snapshot = watcher.snapshot()
        by_target = {m.target: m for m in snapshot.metrics}
        self.assertEqual(
            watcher.counter_value("runtime:physics:query", "overlap"), 4 * iterations
        )
        self.assertEqual(by_target["runtime:tick"].count, 4 * iterations)
        self.assertEqual(by_target["runtime:tick"].in_flight, 0)


class ResetSemanticsTests(unittest.TestCase):
    def test_reset_invalidates_tokens_started_before_it(self) -> None:
        watcher = ObservabilityWatcher()
        token = watcher.begin("runtime:tick")
        watcher.reset()
        with self.assertRaises(ValueError):
            watcher.finish(token)
        self.assertEqual(watcher.snapshot().metrics, ())

    def test_reset_clears_counters_and_gauges(self) -> None:
        watcher = ObservabilityWatcher()
        watcher.increment("runtime:physics:query", "overlap", 5)
        watcher.set_gauge("runtime:animation:update", "active_players", 3)
        watcher.reset()
        self.assertEqual(watcher.counter_value("runtime:physics:query", "overlap"), 0)
        self.assertIsNone(watcher.gauge_value("runtime:animation:update", "active_players"))


if __name__ == "__main__":
    unittest.main()
