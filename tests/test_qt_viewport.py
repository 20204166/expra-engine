"""Qt viewport: canvas item streams, selection callbacks, camera input.

The shared ``ViewportCore`` draws through a canvas API. These tests render scenes into the
Qt ``ViewportPanel`` at a fixed size, inject real Qt mouse/wheel/key events, and check the
canvas item stream, selection callbacks and camera state.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent
from tests.support.qt_app import ensure_qt_app, pump_qt

WIDTH, HEIGHT = 800, 600


class QtHarness:
    def __init__(self, **callbacks: Any) -> None:
        from expra_engine.editor.qt.viewport import ViewportPanel

        ensure_qt_app()
        self.panel = ViewportPanel(**callbacks)
        self.panel.resize(WIDTH, HEIGHT)
        self.panel.show()
        pump_qt(30)
        self.canvas = self.panel._canvas
        assert self.canvas.viewport_size() == (WIDTH, HEIGHT)

    def pump(self) -> None:
        pump_qt(10)

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
    runtime_camera = OrthographicCamera(position=(25.0, 10.0), width=20.0, height=10.0)
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
