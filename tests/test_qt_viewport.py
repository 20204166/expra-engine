"""Qt viewport: canvas item streams, selection callbacks, camera input.

The shared ``ViewportCore`` draws through a canvas API. These tests render scenes into the
Qt ``ViewportPanel`` at a fixed size, inject real Qt mouse/wheel/key events, and check the
canvas item stream, selection callbacks and camera state.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.observability import ObservabilityWatcher, observe_stage
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent
from tests.support.qt_app import ensure_qt_app, pump_qt

WIDTH, HEIGHT = 800, 600


class QtHarness:
    def __init__(self, **callbacks: Any) -> None:
        from expra_engine.editor.qt.viewport import ViewportPanel

        ensure_qt_app()
        self._observer = callbacks.get("observer")
        self.panel = ViewportPanel(**callbacks)
        self.panel.resize(WIDTH, HEIGHT)
        self.panel.show()
        pump_qt(30)
        self.canvas = self.panel._canvas
        assert self.canvas.viewport_size() == (WIDTH, HEIGHT)

    def pump(self) -> None:
        pump_qt(10)

    def pump_until_painted(self, previous_paint_count: int) -> None:
        """Drain the real Qt redraw/paint caused by a motion event without a timer floor."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        assert app is not None
        with observe_stage(self._observer, "editor.viewport.event_pump"):
            for _ in range(64):
                app.processEvents()
                if (
                    not self.panel._redraw_pending
                    and not self.panel._target_dirty
                    and self.canvas.paint_event_count > previous_paint_count
                ):
                    return
        raise RuntimeError("Qt viewport did not finish and paint the motion before return")

    def close(self) -> None:
        self.panel.close()

    def _mouse(self, action: str, x: int, y: int, button: int, state: int) -> None:
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        qbutton = {1: Qt.MouseButton.LeftButton, 2: Qt.MouseButton.MiddleButton}[button]
        modifiers = Qt.KeyboardModifier.NoModifier
        if state & 0x1:
            modifiers |= Qt.KeyboardModifier.ShiftModifier
        if state & 0x4:
            modifiers |= Qt.KeyboardModifier.ControlModifier
        viewport = self.canvas.viewport()
        previous_paint_count = self.canvas.paint_event_count if action == "move" else 0
        if action == "press":
            QTest.mousePress(viewport, qbutton, modifiers, QPoint(x, y))
        elif action == "release":
            QTest.mouseRelease(viewport, qbutton, modifiers, QPoint(x, y))
        else:
            from PySide6.QtCore import QEvent, QPointF
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtWidgets import QApplication

            event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(x, y),
                QPointF(viewport.mapToGlobal(QPoint(x, y))),
                Qt.MouseButton.NoButton,
                qbutton,
                modifiers,
            )
            QApplication.sendEvent(viewport, event)
        if action == "move":
            self.pump_until_painted(previous_paint_count)
        else:
            self.pump()

    def press(self, x: int, y: int, *, button: int = 1, state: int = 0) -> None:
        self._mouse("press", x, y, button, state)

    def motion(self, x: int, y: int, *, button: int = 1, state: int = 0) -> None:
        self._mouse("move", x, y, button, state)

    def release(self, x: int, y: int, *, button: int = 1, state: int = 0) -> None:
        self._mouse("release", x, y, button, state)

    def wheel(self, x: int, y: int, delta: int) -> None:
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication

        viewport = self.canvas.viewport()
        event = QWheelEvent(
            QPointF(x, y),
            QPointF(viewport.mapToGlobal(QPoint(x, y))),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(viewport, event)
        self.pump()

    def key(self, keysym: str, *, control: bool = False) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        keys = {
            "q": Qt.Key.Key_Q,
            "e": Qt.Key.Key_E,
            "r": Qt.Key.Key_R,
            "f": Qt.Key.Key_F,
            "Home": Qt.Key.Key_Home,
            "equal": Qt.Key.Key_Equal,
            "space": Qt.Key.Key_Space,
        }
        modifiers = (
            Qt.KeyboardModifier.ControlModifier if control else Qt.KeyboardModifier.NoModifier
        )
        QTest.keyClick(self.canvas, keys[keysym], modifiers)
        self.pump()

    def item_stream(self) -> list[tuple[Any, ...]]:
        stream = []
        for item in self.canvas.find_all():
            kind = self.canvas.type(item)
            if kind == "image":
                stream.append(("image", self.canvas.itemcget(item, "state")))
                continue
            stream.append(
                (
                    kind,
                    tuple(round(c, 3) for c in self.canvas.coords(item)),
                    tuple(t for t in self.canvas.gettags(item) if t != "current"),
                )
            )
        return stream


@pytest.fixture
def make_harness():
    created: list[Any] = []

    def make(**callbacks: Any):
        harness = QtHarness(**callbacks)
        created.append(harness)
        return harness

    yield make
    for harness in created:
        harness.close()


def _stream_for(build) -> list[tuple[Any, ...]]:
    harness = QtHarness()
    try:
        build(harness)
        return harness.item_stream()
    finally:
        harness.close()


def _roles_scene() -> Scene:
    scene = Scene("Roles")
    scene.create_entity("Camera").add_component(TransformComponent(x=-6, y=3))
    scene.create_entity("Player").add_component(TransformComponent(x=0, y=0))
    rotated = scene.create_entity("Enemy")
    rotated.add_component(TransformComponent(x=5, y=-2, rotation=30))
    rotated.add_component(PrimitiveComponent())
    label = scene.create_entity("Label")
    label.add_component(TransformComponent(x=2, y=4))
    label.add_component(TextComponent("Score", size=12))
    return scene


def _entity_counts(stream: list[tuple[Any, ...]]) -> list[int]:
    counts: dict[str, int] = {}
    for item in stream:
        tags = item[-1]
        if tags and tags[0].startswith("entity:"):
            counts[tags[0]] = counts.get(tags[0], 0) + 1
    return sorted(counts.values())


def test_item_stream_for_roles_selection_and_overlays_off() -> None:
    scene = _roles_scene()
    player = scene.entities[1].entity_id

    def build(h: Any) -> None:
        h.panel.render(scene, player, selected_ids=frozenset({player}))
        h.pump()

    stream = _stream_for(build)
    assert _stream_for(build) == stream, "the same scene renders the same canvas item stream"
    assert sum(1 for item in stream if item[-1] == ("grid",)) == 44
    assert _entity_counts(stream) == [2, 2, 5, 7]  # Enemy, Label, Camera marker, Player marker

    def build_runtime(h: Any) -> None:
        h.panel.render(scene, None, editor_overlays=False)
        h.pump()

    runtime = _stream_for(build_runtime)
    enemy, label = scene.entities[2].entity_id, scene.entities[3].entity_id
    assert runtime == [
        ("image", "hidden"),
        (
            "polygon",
            (592.679, 407.321, 572.679, 372.679, 607.321, 352.679, 627.321, 387.321),
            (f"entity:{enemy}",),
        ),
        ("text", (480.0, 140.0), (f"entity:{label}",)),
    ]


def test_play_canvas_fallback_uses_resolved_camera_for_viewport_mount() -> None:
    from expra_engine.runtime.camera_mount import CameraMountComponent
    from expra_engine.runtime.rendering import OrthographicCamera

    scene = Scene("HUD fallback", camera={"position": [500.0, 500.0], "width": 100.0})
    hud = scene.create_entity("HUD")
    hud.add_component(TransformComponent(x=900.0, y=300.0))
    hud.add_component(CameraMountComponent("top_left", x=16.0, y=-16.0))
    marker = scene.create_entity("Marker", parent_id=hud.entity_id)
    marker.add_component(PrimitiveComponent("rectangle", width=8.0, height=8.0))
    runtime_camera = OrthographicCamera(position=(25.0, 10.0, 0.0), width=20.0, height=10.0)
    harness = QtHarness()
    try:
        harness.panel._pixel_renderer.render = lambda *_args, **_kwargs: None

        harness.panel.render(
            scene,
            None,
            editor_overlays=False,
            resolved_camera=runtime_camera,
        )
        harness.pump()

        marker_items = [
            entry
            for entry in harness.item_stream()
            if entry[-1] == (f"entity:{marker.entity_id}",)
        ]
        assert marker_items
        x0, y0, x1, y1 = marker_items[0][1]
        assert (x0, y0, x1, y1) == pytest.approx((12.0, 12.0, 20.0, 20.0))
    finally:
        harness.close()


def test_canvas_uses_a_semantic_idle_scheduler_instead_of_tk_after_idle() -> None:
    from expra_engine.editor.qt.canvas import QtCanvas

    ensure_qt_app()
    canvas = QtCanvas()
    callbacks: list[str] = []
    try:
        timer = canvas.schedule_idle(lambda: callbacks.append("called"))
        assert timer.isActive()
        assert not hasattr(canvas, "after_idle")
        assert not hasattr(canvas, "configure")
        assert not hasattr(canvas, "focus_set")
        pump_qt(20)
        assert callbacks == ["called"]
    finally:
        canvas.close()


def test_canvas_exposes_semantic_viewport_geometry_not_winfo_methods() -> None:
    from PySide6.QtCore import QPoint

    from expra_engine.editor.qt.canvas import QtCanvas

    ensure_qt_app()
    canvas = QtCanvas()
    try:
        canvas.resize(200, 100)
        canvas.show()
        pump_qt(20)

        assert canvas.viewport_size() == (200, 100)
        global_point = canvas.viewport().mapToGlobal(QPoint(0, 0))
        assert canvas.global_origin() == (global_point.x(), global_point.y())
        assert not any(name.startswith("winfo_") for name in dir(canvas))
    finally:
        canvas.close()


def test_item_stream_for_world_document() -> None:
    world = World(
        "Vey",
        world_id="vey",
        levels=(
            LevelDescriptor("a", "levels/a.level.pb", origin=(0.0, 0.0), bounds=(-10.0, -8.0, 20.0, 16.0)),
            LevelDescriptor("b", "levels/b.level.pb", origin=(40.0, 5.0)),
        ),
        initial_level_id="a",
    )

    def build(h: Any) -> None:
        h.panel.render_world(world, "level:a")
        h.pump()

    stream = _stream_for(build)
    assert [item for item in stream if item[-1] != ("grid",)] == [
        ("image", "hidden"),
        ("rectangle", (0.0, -20.0, 800.0, 620.0), ("world", "level:a", "world:level:a")),
        ("oval", (396.0, 296.0, 404.0, 304.0), ("world", "level:a", "world:level:a")),
        ("text", (400.0, 300.0), ("world", "world:initial:a")),
        ("text", (408.0, 288.0), ("world", "world:level:a")),
        ("oval", (1996.0, 96.0, 2004.0, 104.0), ("world", "level:b", "world:level:b")),
        ("text", (2008.0, 88.0), ("world", "world:level:b")),
    ]


def test_click_shift_click_and_empty_click_selection_callbacks(make_harness) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []
    h = make_harness(on_entity_click=lambda ids, extend: calls.append((ids, extend)))
    scene = _roles_scene()
    h.panel.render(scene, None)
    h.pump()
    enemy = scene.entities[2]
    bounds = h.canvas.bbox(f"entity:{enemy.entity_id}")
    assert bounds is not None
    cx, cy = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
    h.press(cx, cy)
    h.release(cx, cy)
    h.press(cx, cy, state=0x1)
    h.release(cx, cy, state=0x1)
    h.press(WIDTH - 5, HEIGHT - 5)
    h.release(WIDTH - 5, HEIGHT - 5)
    assert calls == [((enemy.entity_id,), False), ((enemy.entity_id,), True), ((), False)]


def test_box_select_wheel_pan_and_camera_keys(make_harness) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []
    cameras: list[dict[str, object]] = []
    h = make_harness(
        on_entity_click=lambda ids, extend: calls.append((ids, extend)),
        on_camera_change=lambda values: cameras.append(dict(values)),
    )
    scene = _roles_scene()
    h.panel.render(scene, None)
    h.pump()
    # box-select across the whole canvas (starting on empty space)
    h.press(2, 2)
    h.motion(WIDTH - 3, HEIGHT - 3)
    h.release(WIDTH - 3, HEIGHT - 3)
    assert calls[0] == ((), False)  # the press on empty space deselects first
    assert len(calls) == 2
    assert set(calls[1][0]) == {entity.entity_id for entity in scene.entities}
    assert not h.canvas.find_withtag("box_select")

    before = h.panel._camera.to_dict()
    h.wheel(WIDTH // 2, HEIGHT // 2, 120)
    zoomed = h.panel._camera.to_dict()
    assert zoomed != before
    h.wheel(WIDTH // 2, HEIGHT // 2, -120)
    assert math.isclose(
        h.panel._camera.to_dict()["zoom"], before["zoom"], rel_tol=1e-9
    )

    pan_before = h.panel._camera.to_dict()
    h.press(100, 100, button=2)
    h.motion(160, 130, button=2)
    h.release(160, 130, button=2)
    assert h.panel._camera.to_dict() != pan_before

    h.key("q")
    rotated = h.panel._camera.to_dict()
    assert math.isclose(rotated["rotation"], math.radians(-15.0))
    h.key("e")
    h.key("r")
    assert h.panel._camera.to_dict()["rotation"] == 0.0
    assert cameras, "camera changes must be reported through on_camera_change"


def test_camera_motion_reprojects_cached_frame_without_reextracting_scene(make_harness) -> None:
    scene = _roles_scene()
    watcher = ObservabilityWatcher()
    h = make_harness(observer=watcher)
    h.panel.render(scene, None)
    h.pump()
    frame = h.panel._target.frame
    previous_camera_position = h.panel._target.render_context.camera.position
    watcher.reset()

    h.press(200, 200, button=2)
    h.motion(260, 230, button=2)
    h.release(260, 230, button=2)

    metrics = {metric.target: metric for metric in watcher.snapshot().metrics}
    assert h.panel._target.frame is frame
    assert h.panel._target.render_context.camera.position != previous_camera_position
    assert metrics.get("render:extract") is None


def test_camera_motion_moves_retained_markers_without_restyling_them(
    make_harness, monkeypatch
) -> None:
    scene = Scene("Marker motion")
    entity = scene.create_entity("Offscreen", entity_id="offscreen")
    entity.add_component(TransformComponent(x=0.0, y=0.0))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    entry = h.panel._marker_entries[entity.entity_id]
    previous_coords = tuple(h.canvas.coords(entry.ids[0]))
    style_calls = []
    original_itemconfig = h.canvas.itemconfig

    def counted_itemconfig(*args, **kwargs):
        style_calls.append(args[0] if args else None)
        return original_itemconfig(*args, **kwargs)

    monkeypatch.setattr(h.canvas, "itemconfig", counted_itemconfig)

    h.press(200, 200, button=2)
    h.motion(260, 230, button=2)
    h.release(260, 230, button=2)

    assert tuple(h.canvas.coords(entry.ids[0])) != previous_coords
    assert style_calls == []


def test_pure_pan_moves_retained_marker_layer_without_per_item_coordinate_writes(
    make_harness, monkeypatch
) -> None:
    scene = Scene("Batched marker pan")
    entity = scene.create_entity("Marker", entity_id="marker")
    entity.add_component(TransformComponent(x=0.0, y=0.0))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    entry = h.panel._marker_entries[entity.entity_id]
    previous = tuple(h.canvas.coords(entry.ids[0]))
    coordinate_writes = []
    original_coords = h.canvas.coords

    def counted_coords(spec, *values):
        if values:
            coordinate_writes.append(spec)
        return original_coords(spec, *values)

    monkeypatch.setattr(h.canvas, "coords", counted_coords)
    h.press(200, 200, button=2)
    h.motion(203, 200, button=2)
    h.release(203, 200, button=2)

    assert tuple(h.canvas.coords(entry.ids[0])) != previous
    assert not set(coordinate_writes).intersection(entry.ids)


def test_pure_pan_retains_collider_overlay_geometry(make_harness, monkeypatch) -> None:
    scene = Scene("Collider pan")
    entity = scene.create_entity("Collider", entity_id="collider")
    entity.add_component(TransformComponent())
    entity.add_component(ColliderComponent(width=4.0, height=2.0))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    entry = h.panel._collider_overlay_entries[entity.entity_id]
    previous = tuple(h.canvas.coords(entry.item_id))
    coordinate_writes = []
    original_coords = h.canvas.coords

    def counted_coords(spec, *values):
        if values:
            coordinate_writes.append(spec)
        return original_coords(spec, *values)

    monkeypatch.setattr(h.canvas, "coords", counted_coords)
    h.press(200, 200, button=2)
    h.motion(203, 200, button=2)
    h.release(203, 200, button=2)

    assert tuple(h.canvas.coords(entry.item_id)) != previous
    assert entry.item_id not in coordinate_writes


def test_camera_pan_reuses_grid_items_instead_of_recreating_them(make_harness, monkeypatch) -> None:
    h = make_harness()
    h.panel.render(Scene("Grid retention"))
    h.pump()
    created = []
    deleted = []
    original_create_line = h.canvas.create_line
    original_delete = h.canvas.delete

    def counted_create_line(*args, **kwargs):
        created.append(args)
        return original_create_line(*args, **kwargs)

    def counted_delete(*args, **kwargs):
        deleted.append(args)
        return original_delete(*args, **kwargs)

    monkeypatch.setattr(h.canvas, "create_line", counted_create_line)
    monkeypatch.setattr(h.canvas, "delete", counted_delete)

    h.panel.pan(1.0, 0.0)

    assert created == []
    assert ("grid",) not in deleted


def test_measured_pan_waits_for_paint_without_fixed_duration_pump(make_harness, monkeypatch) -> None:
    import tests.test_qt_viewport as qt_viewport_tests

    h = make_harness()
    h.panel.render(Scene("Synchronous pan"))
    h.pump()
    h.press(200, 200, button=2)
    previous_position = h.panel._camera.position

    with monkeypatch.context() as scoped:
        scoped.setattr(
            qt_viewport_tests,
            "pump_qt",
            lambda *_args, **_kwargs: pytest.fail("pan completion must not wait on a fixed timer"),
        )
        h.motion(203, 200, button=2)

    assert h.panel._camera.position != previous_position
    assert h.panel._target_dirty is False
    assert h.panel._redraw_pending is False
    h.release(203, 200, button=2)


def test_camera_pan_reuses_scene_entity_name_lookup(make_harness) -> None:
    scene = Scene("Name lookup")
    entity = scene.create_entity("Stable name")
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    name_lookup = h.panel._entity_names

    h.panel.pan(1.0, 0.0)

    assert h.panel._entity_names is name_lookup
    assert h.panel._entity_names[entity.entity_id] == "Stable name"

    entity.name = "Renamed"
    h.panel.render(scene)
    h.pump()

    assert h.panel._entity_names[entity.entity_id] == "Renamed"


def test_offscreen_marker_skips_moves_until_it_can_enter_the_view(make_harness) -> None:
    scene = Scene("Offscreen marker")
    entity = scene.create_entity("Far Away", entity_id="far-away")
    entity.add_component(TransformComponent(x=100.0, y=0.0))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    assert entity.entity_id not in h.panel._marker_entries

    h.panel.pan(1.0, 0.0)
    assert entity.entity_id not in h.panel._marker_entries
    h.panel.pan(89.0, 0.0)
    entry = h.panel._marker_entries[entity.entity_id]
    visible_coords = tuple(h.canvas.coords(entry.ids[0]))

    assert (visible_coords[0] + visible_coords[2]) / 2 == pytest.approx(WIDTH)


def test_offscreen_visual_entity_is_not_represented_as_an_editor_marker(make_harness) -> None:
    scene = Scene("Offscreen visual")
    entity = scene.create_entity("Sprite", entity_id="offscreen-visual")
    entity.add_component(TransformComponent(x=100.0, y=0.0))
    entity.add_component(PrimitiveComponent("rectangle"))
    h = make_harness()

    h.panel.render(scene)
    h.pump()

    assert entity.entity_id in {item.key for item in h.panel._target.frame.items}
    assert entity.entity_id not in {item.key for item in h.panel._target.items}
    assert entity.entity_id not in h.panel._marker_entries


def test_offscreen_marker_restyles_when_selection_changes(make_harness) -> None:
    scene = Scene("Offscreen selection")
    entity = scene.create_entity("Far Away", entity_id="far-away")
    entity.add_component(TransformComponent(x=100.0, y=0.0))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    assert entity.entity_id not in h.panel._marker_entries

    h.panel.render(scene, entity.entity_id)
    h.pump()
    assert entity.entity_id not in h.panel._marker_entries

    h.panel.pan(90.0, 0.0)
    entry = h.panel._marker_entries[entity.entity_id]
    assert h.canvas.itemcget(entry.ids[0], "fill") == h.panel._colors["accent"]


def test_transform_preview_updates_the_rendered_entity_and_spatial_candidate(make_harness) -> None:
    scene = Scene("Transform preview")
    entity = scene.create_entity("Box", entity_id="box")
    transform = TransformComponent()
    entity.add_component(transform)
    entity.add_component(PrimitiveComponent("rectangle"))
    h = make_harness()
    h.panel.render(scene, entity.entity_id, selected_ids=frozenset({entity.entity_id}))
    h.pump()
    entry = h.panel._canvas_items[entity.entity_id]
    previous = tuple(h.canvas.coords(entry.body))

    h.panel._spatial_edit.begin_drag_on_entity(
        entity.entity_id, SimpleNamespace(x=400.0, y=300.0, state=0)
    )
    h.panel._spatial_edit.continue_drag(SimpleNamespace(x=440.0, y=300.0, state=0))
    h.pump()

    assert transform.x == pytest.approx(1.0)
    assert tuple(h.canvas.coords(entry.body)) != previous
    assert entity.entity_id in {item.key for item in h.panel._target.items}


def test_transform_preview_moves_offscreen_visuals_and_markers_across_spatial_cells(make_harness) -> None:
    scene = Scene("Transform crosses visibility cells")
    visual = scene.create_entity("Box", entity_id="box")
    visual.add_component(TransformComponent(x=100.0, y=0.0))
    visual.add_component(PrimitiveComponent("rectangle"))
    marker = scene.create_entity("Marker", entity_id="marker")
    marker.add_component(TransformComponent(x=100.0, y=0.0))
    h = make_harness()
    selected = frozenset({visual.entity_id, marker.entity_id})
    h.panel.render(scene, visual.entity_id, selected_ids=selected)
    h.pump()
    assert visual.entity_id not in h.panel._canvas_items
    assert marker.entity_id not in h.panel._marker_entries

    h.panel._spatial_edit.begin_drag_on_entity(
        visual.entity_id, SimpleNamespace(x=4400.0, y=300.0, state=0)
    )
    h.panel._spatial_edit.continue_drag(SimpleNamespace(x=400.0, y=300.0, state=0))
    h.pump()

    visual_transform = visual.get_component(TransformComponent)
    assert visual_transform is not None
    assert visual_transform.x == pytest.approx(0.0)
    assert visual.entity_id in {item.key for item in h.panel._target.items}
    assert visual.entity_id in h.panel._canvas_items
    assert marker.entity_id in h.panel._marker_entries

    h.panel._spatial_edit.cancel_drag()
    h.pump()
    assert visual.entity_id not in {item.key for item in h.panel._target.items}
    assert visual.entity_id not in h.panel._canvas_items
    assert marker.entity_id not in h.panel._marker_entries


def test_camera_motion_updates_retained_visual_geometry_without_restyling(make_harness, monkeypatch) -> None:
    scene = Scene("Visual motion")
    entity = scene.create_entity("Player", entity_id="player")
    entity.add_component(TransformComponent())
    entity.add_component(PrimitiveComponent("rectangle"))
    h = make_harness()
    h.panel.render(scene)
    h.pump()
    entry = h.panel._canvas_items[entity.entity_id]
    previous_coords = tuple(h.canvas.coords(entry.body))
    style_calls = []
    original_itemconfig = h.canvas.itemconfig

    def counted_itemconfig(*args, **kwargs):
        style_calls.append(args[0] if args else None)
        return original_itemconfig(*args, **kwargs)

    monkeypatch.setattr(h.canvas, "itemconfig", counted_itemconfig)

    h.press(200, 200, button=2)
    h.motion(260, 230, button=2)
    h.release(260, 230, button=2)

    assert tuple(h.canvas.coords(entry.body)) != previous_coords
    assert style_calls == []


def test_resize_keeps_camera_and_reflows_grid(make_harness) -> None:
    h = make_harness()
    scene = _roles_scene()
    h.panel.render(scene, None)
    h.pump()
    grid_before = len(h.canvas.find_withtag("grid"))
    assert grid_before > 0
    zoom = h.panel._camera.to_dict()["zoom"]
    h.panel.resize(400, 300)
    h.pump()
    h.pump()
    assert h.canvas.viewport_size()[0] == 400
    assert len(h.canvas.find_withtag("grid")) < grid_before
    assert h.panel._camera.to_dict()["zoom"] == zoom
