"""Run Expra's real Pygame runtime frame acceptance matrix.

The frame clock starts before Pygame event polling and stops after the real
display flip. ``PygameRuntime``'s intentional frame-cap wait is outside that
interval. The benchmark uses the canonical Engine, RuntimeClock,
``extract_render_frame``, visibility bridge, RenderPlanBuilder, PygameRenderer,
PygameScreenPipeline, ResourceService, and Pygame display path.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.observability import ObservabilityWatcher, summarize_samples
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
)
from expra_engine.runtime.camera_mount import CameraMountComponent
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.event_queue import EventQueue
from expra_engine.runtime.events import FrameUpdate, Idle, Update
from expra_engine.runtime.input import ActionId, PhysicalInput
from expra_engine.runtime.lighting_2d import Light2DComponent
from expra_engine.runtime.physics_world import PhysicsWorld2D
from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider
from expra_engine.runtime.pygame_runtime import PygameRuntime
from expra_engine.runtime.render_extractor import (
    RuntimeRenderFrameCache,
    extract_render_frame,
)
from expra_engine.runtime.render_pipeline import RenderPlanBuilder
from expra_engine.runtime.rendering import OrthographicCamera, RenderContext
from expra_engine.runtime.screen_texture import (
    BackBufferCopyComponent,
    BackBufferCopyMode,
    ScreenTextureComponent,
)
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptRegistry
from expra_engine.runtime.system import RuntimeSystem
from expra_engine.runtime.transform_interpolation import TransformInterpolator
from expra_engine.runtime.visual_components import (
    PrimitiveComponent,
    SpriteComponent,
    TextComponent,
)

TARGET_P95_MS = {1_000: 10.0, 5_000: 20.0, 10_000: 50.0, 50_000: 70.0}
RESOLUTION = (1280, 800)
FRAME_RATE = 60
WARMUP_FRAMES = 30
MEASURED_FRAMES = 120
RUNS = 3
ENTITY_COUNTS = tuple(TARGET_P95_MS)


def _peak_rss_kib() -> int | None:
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / 1024 if sys.platform == "darwin" else peak)


def _allocated_blocks() -> int | None:
    getter = cast(Callable[[], int] | None, getattr(sys, "getallocatedblocks", None))
    return getter() if callable(getter) else None
WORLD_HALF_EXTENT = 160.0
CAMERA_WIDTH = 32.0
CAMERA_HEIGHT = 20.0
_SCENE_SEED = 0xE7A2026


class BenchmarkGameplaySystem(RuntimeSystem):
    """Move the documented dynamic subset and perform a real overlap query."""

    def __init__(
        self,
        moving_entity_ids: tuple[str, ...],
        camera_entity_id: str,
        physics_body_id: str | None,
        *,
        camera_speed: float,
    ) -> None:
        self._moving_entity_ids = moving_entity_ids
        self._camera_entity_id = camera_entity_id
        self._physics_body_id = physics_body_id
        self._camera_speed = camera_speed
        self._moving: list[TransformComponent] = []
        self._camera_transform: TransformComponent | None = None
        self._physics: PhysicsWorld2D | None = None
        self._observer: ObservabilityWatcher | None = None
        self._camera_direction = 1.0
        self.fixed_updates = 0
        self.entities_changed = 0
        self.physics_queries = 0

    def start(self, engine: Engine) -> None:
        scene = engine.active_scene
        if scene is None:
            raise RuntimeError("benchmark Engine has no active Scene")
        self._observer = engine.observer
        self._moving = [
            transform
            for entity_id in self._moving_entity_ids
            if entity_id != self._camera_entity_id
            if (entity := scene.find_entity(entity_id)) is not None
            and (transform := entity.get_component(TransformComponent)) is not None
        ]
        camera_entity = scene.find_entity(self._camera_entity_id)
        self._camera_transform = (
            camera_entity.get_component(TransformComponent) if camera_entity is not None else None
        )
        if self._camera_transform is None:
            raise RuntimeError("benchmark camera target has no TransformComponent")
        self._physics = PhysicsWorld2D(scene, observer=engine.observer)

    def stop(self) -> None:
        self._moving.clear()
        self._camera_transform = None
        self._physics = None
        self._observer = None

    def on_update(self, event: Any, _signal: Any) -> None:
        observer = self._observer
        system_token = (
            observer.begin("runtime:benchmark:gameplay_update")
            if observer is not None
            else None
        )
        self.fixed_updates += 1
        changed = 0
        try:
            for transform in self._moving:
                transform.x += 0.5 * event.time_delta
                changed += 1
            camera = self._camera_transform
            if camera is not None:
                camera.x += self._camera_direction * self._camera_speed * event.time_delta
                edge = WORLD_HALF_EXTENT * 0.5
                if camera.x > edge:
                    camera.x = edge
                    self._camera_direction = -1.0
                elif camera.x < -edge:
                    camera.x = -edge
                    self._camera_direction = 1.0
                changed += 1
            self.entities_changed += changed
            if observer is not None:
                observer.increment("runtime:benchmark:gameplay", "fixed_updates")
                observer.increment("runtime:benchmark:gameplay", "entities_changed", changed)
            if self._physics is not None and self._physics_body_id is not None:
                token = observer.begin("runtime:physics:benchmark_query") if observer else None
                try:
                    self._physics.overlap(self._physics_body_id, include_triggers=False)
                    self.physics_queries += 1
                finally:
                    if observer is not None and token is not None:
                        observer.finish(token)
        finally:
            if observer is not None and system_token is not None:
                observer.finish(system_token)


class _MeasuredClock:
    def __init__(self, clock: Any, on_tick: Callable[[int], None]) -> None:
        self._clock = clock
        self._on_tick = on_tick

    def tick(self, frame_rate: int) -> int:
        elapsed_ms = self._clock.tick(frame_rate)
        self._on_tick(elapsed_ms)
        return elapsed_ms


def _build_scene(
    entity_count: int,
    workload: str,
    texture_id: str,
) -> tuple[Scene, dict[str, Any]]:
    """Build deterministic scene input with the same documented component mix."""
    if entity_count <= 0:
        raise ValueError("entity_count must be positive")
    if workload not in {"large-world", "visible-density"}:
        raise ValueError(f"unknown workload: {workload!r}")

    scene = Scene(f"Runtime frame benchmark {workload} ({entity_count})")
    scene.camera = {
        "position": [0.0, 0.0],
        "width": CAMERA_WIDTH,
        "target_entity_id": "benchmark-camera",
    }
    frames = SpriteFrames2D(
        {
            "idle": SpriteAnimation2D(
                (SpriteFrame2D(texture_id), SpriteFrame2D(texture_id)), speed_fps=8.0
            )
        }
    )
    random_source = random.Random(_SCENE_SEED)
    categories: Counter[str] = Counter()
    moving_ids: list[str] = []
    collider_ids: list[str] = []
    behavior_count = light_count = hud_count = effects = 0

    for index in range(entity_count):
        entity_id = "benchmark-camera" if index == 0 else f"benchmark-{index:06d}"
        entity = scene.create_entity(f"entity-{index:06d}", entity_id=entity_id)
        if index == 0:
            x = y = 0.0
        elif workload == "large-world":
            x = random_source.uniform(-WORLD_HALF_EXTENT, WORLD_HALF_EXTENT)
            y = random_source.uniform(-WORLD_HALF_EXTENT, WORLD_HALF_EXTENT)
        else:
            x = random_source.uniform(-CAMERA_WIDTH * 0.48, CAMERA_WIDTH * 0.48)
            y = random_source.uniform(-CAMERA_HEIGHT * 0.48, CAMERA_HEIGHT * 0.48)
        entity.add_component(TransformComponent(x=x, y=y))

        category = index % 100
        if category < 60:
            categories["primitive"] += 1
            shape = ("rectangle", "circle", "rounded_rectangle", "polygon", "line")[index % 5]
            if shape == "polygon":
                primitive = PrimitiveComponent(
                    "polygon",
                    points=((-0.6, -0.5), (0.7, -0.4), (0.2, 0.8)),
                    fill=(0.3, 0.7, 0.9, 1.0),
                )
            elif shape == "line":
                primitive = PrimitiveComponent(
                    "line", points=((-0.6, -0.5), (0.7, 0.6)), thickness=1.2
                )
            else:
                primitive = PrimitiveComponent(
                    shape,
                    width=1.2,
                    height=0.9,
                    radius=0.25 if shape == "rounded_rectangle" else None,
                    fill=(0.3, 0.7, 0.9, 1.0),
                )
            entity.add_component(primitive)
        elif category < 80:
            categories["sprite"] += 1
            entity.add_component(SpriteComponent(texture_id, width=1.2, height=1.0))
        elif category < 85:
            categories["animated_sprite"] += 1
            entity.add_component(AnimatedSprite2DComponent(frames, autoplay="idle"))
        else:
            categories["nonvisual"] += 1
            if category == 85:
                entity.add_component(ColliderComponent(width=1.0, height=1.0))
                categories["collider"] += 1
                collider_ids.append(entity_id)
            if category >= 90 and index % 200 == 199:
                entity.add_component(
                    ScriptComponent(
                        "project://scripts/runtime_benchmark.py", "BenchmarkBehaviour"
                    )
                )
                behavior_count += 1

        if index % 20 == 0:
            moving_ids.append(entity_id)
        if 60 <= category < 80 and index % 1000 == 65:
            entity.add_component(Light2DComponent(radius=8.0, energy=0.5, falloff=2.0))
            light_count += 1
        if 60 <= category < 80 and index % 1000 == 66:
            entity.add_component(CameraMountComponent("top_left", x=8.0, y=8.0))
            entity.add_component(TextComponent("BENCH", size=12.0))
            hud_count += 1
        if index == 0:
            entity.add_component(
                BackBufferCopyComponent(
                    copy_mode=BackBufferCopyMode.VIEWPORT,
                    capture_id="benchmark-screen",
                    layer=-100,
                    phase="transparent",
                )
            )
            effects += 1
        elif index == 1:
            entity.add_component(
                ScreenTextureComponent(
                    capture_id="benchmark-screen", width=3.0, height=2.0, layer=100
                )
            )
            effects += 1

    return scene, {
        "entity_count": entity_count,
        "component_counts": dict(sorted(categories.items())),
        "dynamic_entities": len(moving_ids),
        "dynamic_fraction": len(moving_ids) / entity_count,
        "behavior_components": behavior_count,
        "lights": light_count,
        "hud_roots": hud_count,
        "screen_effect_components": effects,
        "colliders": len(collider_ids),
        "moving_entity_ids": tuple(moving_ids),
        "camera_entity_id": "benchmark-camera",
        "physics_body_id": collider_ids[0] if collider_ids else None,
    }


def _summary_ms(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        return {}
    summary = summarize_samples(tuple(samples))
    return {key: value if key == "outliers" else value * 1000.0 for key, value in summary.items()}


def _metrics(observer: ObservabilityWatcher) -> dict[str, Any]:
    snapshot = observer.snapshot()
    return {
        metric.target: {
            "count": metric.count,
            "failures": metric.failures,
            "distribution_ms": _summary_ms(list(metric.samples)),
            "counters": dict(metric.counters),
            "gauges": dict(metric.gauges),
        }
        for metric in snapshot.metrics
    }


def _instrument_pipeline(observer: ObservabilityWatcher) -> Any:
    from expra_engine.runtime import render_pipeline

    original_visibility = render_pipeline.filter_visible_items
    original_plan_descriptor = RenderPlanBuilder.__dict__["from_frame"]
    original_plan = RenderPlanBuilder.from_frame
    original_publish_item = EventQueue._publish_item
    original_capture_scene = TransformInterpolator.capture_scene

    def measure_visibility(items: Any, context: Any) -> tuple[Any, ...]:
        candidate_count = len(items) if hasattr(items, "__len__") else None
        started = time.perf_counter()
        result = original_visibility(items, context)
        observer.record("render:visibility", time.perf_counter() - started)
        if candidate_count is not None:
            observer.increment("render:visibility", "candidates", candidate_count)
        observer.increment("render:visibility", "visible_items", len(result))
        return result

    def measure_plan(
        frame: Any,
        context: Any = None,
        *,
        visible_items: tuple[Any, ...] | None = None,
    ) -> Any:
        started = time.perf_counter()
        result = original_plan(frame, context, visible_items=visible_items)
        observer.record("render:plan", time.perf_counter() - started)
        observer.increment("render:plan", "operations", len(result.operations))
        observer.increment("render:plan", "draw_items", len(result.draw_items))
        observer.increment("render:plan", "capture_ids", len(result.capture_ids))
        return result

    def measure_dispatch(queue: EventQueue, item: Any) -> None:
        event = getattr(item, "event", item)
        if isinstance(event, Update):
            target = "runtime:fixed"
        elif isinstance(event, FrameUpdate):
            target = "runtime:update"
        elif isinstance(event, Idle):
            target = "runtime:idle"
        else:
            original_publish_item(queue, item)
            return
        started = time.perf_counter()
        try:
            original_publish_item(queue, item)
        finally:
            observer.record(target, time.perf_counter() - started)

    def measure_capture_scene(
        interpolator: TransformInterpolator, scene: Scene | None
    ) -> None:
        dirty_count = len(scene._pending_transform_entities) if scene is not None else 0
        started = time.perf_counter()
        try:
            original_capture_scene(interpolator, scene)
        finally:
            observer.record("runtime:interpolation:capture", time.perf_counter() - started)
            observer.increment(
                "runtime:interpolation:capture", "dirty_entities", dirty_count
            )

    render_pipeline.filter_visible_items = measure_visibility
    RenderPlanBuilder.from_frame = staticmethod(measure_plan)
    EventQueue._publish_item = measure_dispatch  # type: ignore[reportAttributeAccessIssue]
    TransformInterpolator.capture_scene = measure_capture_scene  # type: ignore[reportAttributeAccessIssue]

    def restore() -> None:
        render_pipeline.filter_visible_items = original_visibility
        RenderPlanBuilder.from_frame = original_plan_descriptor
        EventQueue._publish_item = original_publish_item
        TransformInterpolator.capture_scene = original_capture_scene

    return restore


def _prepare_project(root: Path) -> tuple[Project, str]:
    project = Project.create("Runtime Frame Benchmark", root / "project")
    texture_source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "texture_probe.png"
    if not texture_source.is_file():
        raise FileNotFoundError(f"required benchmark texture fixture is missing: {texture_source}")
    texture_id = str(project.import_asset(texture_source, "benchmark.png"))
    (project.scripts_dir / "runtime_benchmark.py").write_text(
        "from expra_engine.runtime.behaviour import Behaviour\n\n"
        "class BenchmarkBehaviour(Behaviour):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fixed_updates = 0\n"
        "        self.input_events = 0\n\n"
        "    def on_fixed_update(self, dt):\n"
        "        self.fixed_updates += 1\n\n"
        "    def on_input(self, event, signal=None):\n"
        "        self.input_events += 1\n"
        "        return False\n",
        encoding="utf-8",
    )
    project.set_input_binding("benchmark_pulse", "keyboard:space")
    return project, texture_id


def _run_trial(
    pygame: Any,
    project: Project,
    scene: Scene,
    details: dict[str, Any],
    workload: str,
    run_index: int,
    warmup_frames: int,
    measured_frames: int,
    progress: bool = False,
) -> dict[str, Any]:
    observer = ObservabilityWatcher(sample_limit=warmup_frames + measured_frames + 16)
    engine = Engine(observer=observer)
    engine.set_project(project)
    engine.set_script_registry(ScriptRegistry(project.path))
    engine.set_scene(scene)
    gameplay = BenchmarkGameplaySystem(
        details["moving_entity_ids"],
        details["camera_entity_id"],
        details["physics_body_id"],
        camera_speed=8.0 if workload == "large-world" else 0.5,
    )
    engine.add_system(gameplay)
    engine.input_map.bind(ActionId("benchmark_pulse"), PhysicalInput("keyboard", "space"))

    provider = PygameResourceProvider(
        pygame, project.resource_service(observer=observer), observer=observer
    )
    renderer = PygameRenderer(
        pygame,
        None,
        screen_size=RESOLUTION,
        resource_provider=provider,
        observer=observer,
    )
    render_cache = RuntimeRenderFrameCache()
    runtime = PygameRuntime(
        engine,
        renderer,
        pygame_module=pygame,
        size=RESOLUTION,
        frame_rate=FRAME_RATE,
        camera=OrthographicCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT),
        frame_factory=lambda current, dt: _make_frame(
            current, dt, observer, renderer.context, render_cache
        ),
    )

    state: dict[str, Any] = {
        "frame_index": 0,
        "frame_start": None,
        "frame_wall_seconds": [],
        "present_seconds": [],
        "event_seconds": [],
        "allocation_block_deltas": [],
        "allocation_blocks_before": None,
        "frame_item_counts": [],
        "fixed_steps_per_frame": [],
        "engine_dt_seconds": [],
        "fixed_updates_before_frame": 0,
        "next_engine_dt_seconds": None,
        "input_events": 0,
        "runtime_setup_to_first_poll_ms": None,
    }
    original_event_get = pygame.event.get
    original_event_post = pygame.event.post
    original_flip = pygame.display.flip
    original_poll = runtime._poll_events
    original_clock = runtime.clock
    restore_pipeline = _instrument_pipeline(observer)
    gc_before = gc.get_stats()
    peak_rss_before = _peak_rss_kib()

    def event_get(*args: Any, **kwargs: Any) -> list[Any]:
        events = original_event_get(*args, **kwargs)
        state["input_events"] += len(events)
        return events

    def poll_events() -> None:
        frame_index = state["frame_index"]
        if frame_index % 60 == 0:
            original_event_post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        elif frame_index % 60 == 1:
            original_event_post(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
        started = time.perf_counter()
        state["allocation_blocks_before"] = _allocated_blocks()
        state["frame_start"] = started
        state["fixed_updates_before_frame"] = gameplay.fixed_updates
        state["engine_dt_seconds"].append(state["next_engine_dt_seconds"])
        if frame_index == 0:
            state["runtime_setup_to_first_poll_ms"] = (
                started - state["runtime_started"]
            ) * 1000.0
        try:
            original_poll()
        finally:
            state["event_seconds"].append(time.perf_counter() - started)

    def display_flip(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = original_flip(*args, **kwargs)
        finished = time.perf_counter()
        state["present_seconds"].append(finished - started)
        blocks_before = state["allocation_blocks_before"]
        blocks_after = _allocated_blocks()
        if blocks_before is not None and blocks_after is not None:
            state["allocation_block_deltas"].append(blocks_after - blocks_before)
        else:
            state["allocation_block_deltas"].append(None)
        frame_started = state["frame_start"]
        if frame_started is not None:
            state["frame_wall_seconds"].append(finished - frame_started)
            state["fixed_steps_per_frame"].append(
                gameplay.fixed_updates - state["fixed_updates_before_frame"]
            )
        state["frame_start"] = None
        state["frame_index"] += 1
        if progress and state["frame_index"] in {
            1,
            2,
            3,
            4,
            5,
            10,
            warmup_frames,
            warmup_frames + 1,
            warmup_frames + 10,
            warmup_frames + measured_frames,
        }:
            completed = state["frame_index"]
            phase = "warmup" if completed <= warmup_frames else "measured"
            frame_wall_ms = state["frame_wall_seconds"][-1] * 1000.0
            fixed_steps = state["fixed_steps_per_frame"][-1]
            engine_dt_ms = float(state["engine_dt_seconds"][-1] or 0.0) * 1000.0
            print(
                f"{workload} {len(scene.entities)} run {run_index}: "
                f"{phase} frame {completed}/{warmup_frames + measured_frames}; "
                f"dt={engine_dt_ms:.2f}ms fixed_steps={fixed_steps} "
                f"frame={frame_wall_ms:.2f}ms",
                flush=True,
            )
        return result

    def clock_tick(elapsed_ms: int) -> None:
        state["next_engine_dt_seconds"] = elapsed_ms / 1000.0

    pygame.event.get = event_get
    pygame.display.flip = display_flip
    runtime._poll_events = poll_events
    runtime.clock = _MeasuredClock(original_clock, clock_tick)
    try:
        engine_started = time.perf_counter()
        if not engine.play():
            raise RuntimeError("Engine refused to enter PLAY for the runtime benchmark")
        play_startup_ms = (time.perf_counter() - engine_started) * 1000.0
        if progress:
            print(
                f"{workload} {details['entity_count']} run {run_index}: "
                f"Engine.play complete in {play_startup_ms:.1f} ms; starting warm-up",
                flush=True,
            )
        runtime_frames = warmup_frames + measured_frames

        def frame_factory(current_engine: Engine, dt: float) -> Any:
            frame = _make_frame(
                current_engine,
                dt,
                observer,
                renderer.context,
                render_cache,
            )
            state["frame_item_counts"].append(len(frame.items))
            if state["frame_index"] + 1 >= runtime_frames:
                runtime.stop()
            return frame

        runtime.frame_factory = frame_factory
        state["runtime_started"] = time.perf_counter()
        runtime.run()
        if len(state["frame_wall_seconds"]) != runtime_frames:
            raise RuntimeError(
                f"runtime stopped early: expected {runtime_frames} frames, "
                f"got {len(state['frame_wall_seconds'])}"
            )
        warm_start = warmup_frames
        wall = state["frame_wall_seconds"][warm_start:]
        present = state["present_seconds"][warm_start:]
        events = state["event_seconds"][warm_start:]
        fixed_steps = state["fixed_steps_per_frame"][warm_start:]
        engine_dt = state["engine_dt_seconds"][warm_start:]
        allocation_deltas = state["allocation_block_deltas"][warm_start:]
        peak_rss_after = _peak_rss_kib()
        return {
            "run": run_index,
            "workload": workload,
            "scene": {
                key: value
                for key, value in details.items()
                if key not in {"moving_entity_ids", "camera_entity_id", "physics_body_id"}
            },
            "engine_play_startup_ms": play_startup_ms,
            "runtime_setup_to_first_poll_ms": state["runtime_setup_to_first_poll_ms"],
            "cold_first_frame_ms": state["frame_wall_seconds"][0] * 1000.0,
            "steady_frame_wall_ms": _summary_ms(wall),
            "event_processing_ms": _summary_ms(events),
            "net_allocated_blocks_per_frame": summarize_samples(
                tuple(value for value in allocation_deltas if value is not None)
            ),
            "allocation_count_metric": "CPython net allocated blocks; freed temporary allocations are not counted",
            "progress_logging": progress,
            "display_present_ms": _summary_ms(present),
            "measured_frames": len(wall),
            "fixed_steps_per_frame": summarize_samples(
                tuple(float(value) for value in fixed_steps)
            ),
            "mean_fixed_steps_per_frame": sum(fixed_steps) / len(fixed_steps),
            "engine_dt_ms": _summary_ms(
                [float(value) for value in engine_dt if value is not None]
            ),
            "input_events_total": state["input_events"],
            "extracted_render_items_avg": sum(state["frame_item_counts"][warm_start:]) / len(wall),
            "gameplay_fixed_updates": gameplay.fixed_updates,
            "dynamic_entity_changes": gameplay.entities_changed,
            "physics_queries": gameplay.physics_queries,
            "resource_cache_entries": len(provider._textures),
            "lighting_cache_entries": renderer._lighting_pass.cache_entries,
            "lighting_cache_bytes": renderer._lighting_pass.cache_bytes,
            "process_peak_rss_kib": peak_rss_after,
            "peak_rss_growth_kib": (
                max(0, peak_rss_after - peak_rss_before)
                if peak_rss_before is not None and peak_rss_after is not None
                else None
            ),
            "gc_stats": [
                {key: after[key] - before[key] for key in before}
                for before, after in zip(gc_before, gc.get_stats(), strict=True)
            ],
            "observability": _metrics(observer),
        }
    finally:
        runtime.stop()
        if engine.run_state.value != "edit":
            engine.stop()
        pygame.event.get = original_event_get
        pygame.display.flip = original_flip
        runtime._poll_events = original_poll
        runtime.clock = original_clock
        restore_pipeline()
        pygame.quit()


def _make_frame(
    engine: Engine,
    dt: float,
    observer: ObservabilityWatcher,
    visibility_context: RenderContext | None = None,
    render_cache: RuntimeRenderFrameCache | None = None,
) -> Any:
    scene = engine.active_scene
    if scene is None:
        raise RuntimeError("runtime benchmark has no active Scene")
    started = time.perf_counter()
    extraction_args = {
        "elapsed": dt,
        "interpolator": engine.transform_interpolator,
        "interpolation_fraction": engine.interpolation_fraction,
        "animated_players": engine.animated_sprite_system.players,
    }
    frame = (
        render_cache.extract(scene, context=visibility_context, **extraction_args)
        if render_cache is not None
        else extract_render_frame(scene, visibility_context=visibility_context, **extraction_args)
    )
    observer.record("render:extract", time.perf_counter() - started)
    observer.increment("render:extract", "render_items", len(frame.items))
    observer.increment("render:extract", "lights", len(frame.lights))
    observer.increment("render:extract", "effects", len(frame.submissions) - len(frame.items))
    return frame


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--workload", choices=("all", "large-world", "visible-density"), default="all")
    parser.add_argument("--entity-count", type=int, choices=ENTITY_COUNTS)
    parser.add_argument("--runs", type=int, choices=(1, RUNS), default=RUNS)
    parser.add_argument("--warmup-frames", type=int, default=WARMUP_FRAMES)
    parser.add_argument("--measured-frames", type=int, default=MEASURED_FRAMES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    if args.resume and args.output is None:
        parser.error("--resume requires --output")
    if args.warmup_frames < WARMUP_FRAMES:
        parser.error(f"--warmup-frames must be at least {WARMUP_FRAMES}")
    if args.measured_frames < MEASURED_FRAMES:
        parser.error(f"--measured-frames must be at least {MEASURED_FRAMES}")
    return args


def _description() -> dict[str, Any]:
    return {
        "target_p95_ms": {str(size): target for size, target in TARGET_P95_MS.items()},
        "resolution": list(RESOLUTION),
        "frame_rate_cap": FRAME_RATE,
        "runs_per_size": RUNS,
        "warmup_frames": WARMUP_FRAMES,
        "measured_frames": MEASURED_FRAMES,
        "workloads": ["large-world", "visible-density"],
        "component_mix_percent": {
            "primitive": 60,
            "sprite": 20,
            "animated_sprite": 5,
            "nonvisual": 15,
            "collider": 1,
            "moving_transform": 5,
            "behavior": 0.5,
            "light": 0.1,
            "viewport_hud": 0.1,
        },
        "primary_scope": "event polling through actual Pygame display flip; FPS-cap sleeps excluded",
        "note": "visibility candidates and RenderPlanBuilder are exercised by screen-effect submissions; counts in each result expose any workload reductions",
        "allocation_metric": "CPython sys.getallocatedblocks delta per frame is net retained blocks, not total allocation churn",
    }


def _validate_resume_report(
    report: dict[str, Any],
    *,
    baseline_commit: str,
    source_fingerprint: str,
    contract: dict[str, Any],
    matrix_scope: dict[str, Any],
) -> list[dict[str, Any]]:
    if report.get("baseline_commit") != baseline_commit:
        raise ValueError("cannot resume: baseline commit does not match")
    if report.get("source_fingerprint") != source_fingerprint:
        raise ValueError("cannot resume: source fingerprint does not match")
    if report.get("contract") != contract:
        raise ValueError("cannot resume: benchmark contract does not match")
    if report.get("matrix_scope") != matrix_scope:
        raise ValueError("cannot resume: matrix scope does not match")
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("cannot resume: report results must be a list")

    workloads = set(matrix_scope["workloads"])
    entity_counts = set(matrix_scope["entity_counts"])
    run_count = int(matrix_scope["runs_per_case"])
    seen: set[tuple[str, int, int]] = set()
    for result in results:
        try:
            key = (result["workload"], result["scene"]["entity_count"], result["run"])
        except (KeyError, TypeError) as exc:
            raise ValueError("cannot resume: report contains a malformed result") from exc
        if key[0] not in workloads or key[1] not in entity_counts or not 1 <= key[2] <= run_count:
            raise ValueError("cannot resume: report result is outside the requested matrix")
        if key in seen:
            raise ValueError("cannot resume: report contains a duplicate trial")
        seen.add(key)
    return results


def _source_fingerprint() -> str:
    repository_root = Path(__file__).resolve().parents[1]
    roots = (repository_root / "src", repository_root / "native")
    source_suffixes = {".py", ".pyx", ".pxd", ".rs", ".toml", ".lock"}
    paths = [
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix in source_suffixes
    ]
    paths.append(Path(__file__).resolve())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(repository_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    args = _arguments()
    if args.describe:
        print(json.dumps(_description(), indent=2, sort_keys=True))
        return 0
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    workloads = (
        ("large-world", "visible-density")
        if args.workload == "all"
        else (args.workload,)
    )
    entity_counts = ENTITY_COUNTS if args.entity_count is None else (args.entity_count,)
    output: dict[str, Any] = {
        "python": sys.version,
        "pygame": pygame.version.ver,
        "platform": platform.platform(),
        "baseline_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_fingerprint": _source_fingerprint(),
        "dirty": bool(subprocess.check_output(["git", "status", "--short"], text=True).strip()),
        "contract": _description(),
        "matrix_scope": {
            "workloads": list(workloads),
            "entity_counts": list(entity_counts),
            "runs_per_case": args.runs,
            "progress_reporting": args.progress,
        },
        "results": [],
        "acceptance": "INCOMPLETE",
    }
    if args.resume and args.output is not None and args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        output["results"] = _validate_resume_report(
            previous,
            baseline_commit=output["baseline_commit"],
            source_fingerprint=output["source_fingerprint"],
            contract=output["contract"],
            matrix_scope=output["matrix_scope"],
        )
        for environment_key in ("python", "pygame", "platform", "dirty"):
            if previous.get(environment_key) != output[environment_key]:
                raise ValueError(f"cannot resume: {environment_key} does not match")
    completed = {
        (result["workload"], result["scene"]["entity_count"], result["run"])
        for result in output["results"]
    }
    if args.output is not None:
        args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="expra_runtime_frame_") as directory:
        if args.progress:
            print("Preparing temporary Project and texture resource", flush=True)
        project, texture_id = _prepare_project(Path(directory))
        if args.progress:
            print("Temporary Project ready", flush=True)
        for workload in workloads:
            for count in entity_counts:
                if args.progress:
                    print(f"{workload} {count}: building deterministic Scene", flush=True)
                scene, details = _build_scene(count, workload, texture_id)
                if args.progress:
                    print(f"{workload} {count}: Scene ready", flush=True)
                for run_index in range(1, args.runs + 1):
                    trial_key = (workload, count, run_index)
                    if trial_key in completed:
                        print(f"resume: skipping completed {workload} {count} run {run_index}")
                        continue
                    run = _run_trial(
                        pygame,
                        project,
                        scene,
                        details,
                        workload,
                        run_index,
                        args.warmup_frames,
                        args.measured_frames,
                        args.progress,
                    )
                    target = TARGET_P95_MS[count]
                    run["target_p95_ms"] = target
                    run["target_pass"] = run["steady_frame_wall_ms"]["p95"] <= target
                    output["results"].append(run)
                    completed.add(trial_key)
                    output["acceptance"] = (
                        "PERFORMANCE TARGET NOT MET"
                        if any(not item["target_pass"] for item in output["results"])
                        else "INCOMPLETE"
                    )
                    if args.output is not None:
                        args.output.write_text(
                            json.dumps(output, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    print(
                        f"{workload} {count} run {run_index}: "
                        f"p50={run['steady_frame_wall_ms']['p50']:.3f}ms "
                        f"p95={run['steady_frame_wall_ms']['p95']:.3f}ms "
                        f"target={target:.1f}ms pass={run['target_pass']}"
                    )
    full_matrix = (
        workloads == ("large-world", "visible-density")
        and entity_counts == ENTITY_COUNTS
        and args.runs == RUNS
        and not args.progress
    )
    expected_results = len(workloads) * len(entity_counts) * args.runs
    output["acceptance"] = (
        "PERFORMANCE TARGET NOT MET"
        if any(not result["target_pass"] for result in output["results"])
        else (
            "PASS"
            if full_matrix and len(output["results"]) == expected_results
            else "INCOMPLETE"
        )
    )
    text = json.dumps(output, indent=2, sort_keys=True)
    if args.output is None:
        print(text)
    else:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote runtime benchmark report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
