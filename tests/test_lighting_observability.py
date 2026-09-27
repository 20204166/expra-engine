"""Lighting and material-response observability: bounded timing spans, stable targets."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.rendering import (
    Color,
    LightDescriptor,
    RenderContext,
    RenderFrame,
    Viewport,
)


def _make_watcher() -> ObservabilityWatcher:
    return ObservabilityWatcher(sample_limit=64)


def _metric(watcher: ObservabilityWatcher, target: str):
    return next((m for m in watcher.snapshot().metrics if m.target == target), None)


def _fake_pygame() -> Any:
    class _FakeFont:
        def render(self, *a: Any, **k: Any) -> Any:
            return SimpleNamespace(get_size=lambda: (0, 0))

    class _FakeDraw:
        def rect(self, *a: Any, **k: Any) -> None:
            pass

    class _FakeSurface:
        _data: list[Any]

        def __init__(self) -> None:
            self._data = []

        def get_size(self) -> tuple[int, int]:
            return (200, 150)

        def fill(self, *a: Any, **k: Any) -> None:
            pass

        def blit(self, *a: Any, **k: Any) -> None:
            pass

        def subsurface(self, *a: Any, **k: Any) -> _FakeSurface:
            return _FakeSurface()

        def copy(self) -> _FakeSurface:
            return _FakeSurface()

    class _FakePygame:
        BLEND_RGBA_ADD = 0
        BLEND_RGBA_MULT = 0
        SRCALPHA = 0

        class draw(_FakeDraw):
            pass

        class font:
            @staticmethod
            def Font(*a: Any, **k: Any) -> _FakeFont:
                return _FakeFont()

        @staticmethod
        def Surface(size: tuple[int, int], *a: Any, **k: Any) -> _FakeSurface:
            return _FakeSurface()

    return _FakePygame()


def _fake_surface() -> Any:
    class _S:
        def fill(self, *a: Any, **k: Any) -> None:
            pass

        def blit(self, *a: Any, **k: Any) -> None:
            pass

        def get_size(self) -> tuple[int, int]:
            return (200, 150)

        def subsurface(self, *a: Any) -> _S:
            return _S()

        def copy(self) -> _S:
            return _S()

    return _S()


def _simple_light() -> LightDescriptor:
    return LightDescriptor(
        entity_id="torch",
        kind="point",
        position=(0.0, 0.0, 0.0),
        color=Color(1.0, 1.0, 0.8, 1.0),
        energy=1.0,
        radius=10.0,
        falloff=1.0,
    )


def _renderer_with_lights(watcher: ObservabilityWatcher):
    from expra_engine.runtime.pygame_renderer import PygameRenderer

    pygame = _fake_pygame()
    surface = _fake_surface()
    renderer = PygameRenderer(pygame, surface, clear_color=None, observer=watcher)
    renderer.start(RenderContext(Viewport(0, 0, 200, 150)))
    return renderer


# ─── render:lighting:compose timing span ──────────────────────────────────────


def test_render_lighting_compose_span_recorded_with_lights() -> None:
    """render:lighting:compose must record a timing span when lights are composited."""
    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)
    frame = RenderFrame(lights=(_simple_light(),), lighting_enabled=True)

    renderer.render(frame)

    metric = _metric(watcher, "render:lighting:compose")
    assert metric is not None and metric.count >= 1, (
        "render:lighting:compose span not recorded; lighting composite cost must be measurable"
    )


def test_render_lighting_compose_span_absent_with_no_lights() -> None:
    """render:lighting:compose must NOT record a span when no lights are in the frame."""
    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)
    frame = RenderFrame(lights=(), lighting_enabled=True)

    renderer.render(frame)

    metric = _metric(watcher, "render:lighting:compose")
    assert metric is None or metric.count == 0, (
        "render:lighting:compose must only be recorded when lights are actually composited"
    )


# ─── render:lighting counters ─────────────────────────────────────────────────


def test_render_lighting_lights_considered_counter() -> None:
    """render:lighting lights_considered counter must be set when lights exist."""
    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)
    frame = RenderFrame(lights=(_simple_light(),), lighting_enabled=True)

    renderer.render(frame)

    metric = _metric(watcher, "render:lighting")
    assert metric is not None, "render:lighting metric not recorded"
    counters = dict(metric.counters)
    assert counters.get("lights_considered", 0) >= 1, (
        f"lights_considered not set; counters: {counters}"
    )


def test_render_lighting_no_lights_no_counter() -> None:
    """render:lighting must not be recorded if no lights exist in the frame."""
    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)
    frame = RenderFrame(lights=(), lighting_enabled=True)

    renderer.render(frame)

    metric = _metric(watcher, "render:lighting")
    if metric is not None:
        counters = dict(metric.counters)
        assert counters.get("lights_considered", 0) == 0, (
            "lights_considered should be 0 when no lights in frame"
        )


# ─── material response counters ───────────────────────────────────────────────


def test_render_material_light_counters_recorded() -> None:
    """render:material-light material_items_total counter must be set when material items exist."""
    from expra_engine.runtime.material_lighting import MaterialLightResponse
    from expra_engine.runtime.rendering import MaterialDescriptor, RenderItem, Transform

    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)

    response = MaterialLightResponse(mode="lit")
    from expra_engine.runtime.rendering import PrimitiveDescriptor

    item = RenderItem(
        key="sprite",
        primitive=PrimitiveDescriptor("rectangle", (1.0, 1.0)),
        transform=Transform((0.0, 0.0, 0.0), 0.0, (1.0, 1.0, 1.0)),
        material=MaterialDescriptor(light_response=response),
    )
    frame = RenderFrame(
        items=(item,),
        lights=(_simple_light(),),
        lighting_enabled=True,
    )

    renderer.render(frame)

    metric = _metric(watcher, "render:material-light")
    assert metric is not None, "render:material-light metric not recorded"
    counters = dict(metric.counters)
    assert counters.get("material_items_total", 0) >= 1, (
        f"material_items_total not set; counters: {counters}"
    )


# ─── stable cardinality — no per-light or per-entity target names ──────────────


def test_render_target_names_do_not_contain_entity_ids() -> None:
    """Observer targets must never include entity IDs or light IDs."""
    watcher = _make_watcher()
    renderer = _renderer_with_lights(watcher)
    frame = RenderFrame(lights=(_simple_light(),), lighting_enabled=True)

    renderer.render(frame)

    for m in watcher.snapshot().metrics:
        assert "torch" not in m.target, (
            f"Entity/light ID 'torch' appeared in metric target: {m.target!r}"
        )


# ─── observer=None fast path ──────────────────────────────────────────────────


def test_renderer_without_observer_does_not_crash_with_lights() -> None:
    """PygameRenderer with observer=None must render without crashing."""
    from expra_engine.runtime.pygame_renderer import PygameRenderer

    renderer = PygameRenderer(_fake_pygame(), _fake_surface(), clear_color=None)
    renderer.start(RenderContext(Viewport(0, 0, 200, 150)))

    frame = RenderFrame(lights=(_simple_light(),), lighting_enabled=True)
    renderer.render(frame)  # must not raise
