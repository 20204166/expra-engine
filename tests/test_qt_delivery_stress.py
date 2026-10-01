"""Stress of the Qt worker->UI delivery path (QtDeliveryQueue) after the cross-thread QTimer fix.

Invariants proven here:
  * no segfault, and no Qt log message at all (in particular no "QObject::... another thread"
    timer warnings) across every scenario;
  * a callback delivered to the UI thread never touches a destroyed widget (exceptions raised
    inside delivered callbacks are recorded before the queue's own suppression and must be empty);
  * work finishing after the window closed is dropped, never delivered;
  * delivery always happens on the thread that owns the queue.
"""

from __future__ import annotations

import gc
import threading
from pathlib import Path

import pytest

from expra_engine.core.engine import EngineRunState
from expra_engine.core.project import Project
from tests.support.qt_app import ensure_qt_app, pump_qt, qt_available, wait_until
from tests.support.qt_editor import make_editor

pytestmark = [
    pytest.mark.skipif(not qt_available(), reason="PySide6 not installed"),
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]

_BENIGN = ("propagateSizeHints",)  # offscreen-platform notice, unrelated to timers/threads


@pytest.fixture
def guard(monkeypatch):
    """Capture Qt log output and exceptions raised inside delivered callbacks."""
    from PySide6.QtCore import qInstallMessageHandler

    from expra_engine.editor.qt.delivery import QtDeliveryQueue

    ensure_qt_app()
    messages: list[str] = []
    errors: list[str] = []
    qInstallMessageHandler(lambda _mode, _ctx, message: messages.append(message))

    original = QtDeliveryQueue.__call__

    def recording(self, callback):
        def guarded():
            try:
                callback()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                raise

        original(self, guarded)

    monkeypatch.setattr(QtDeliveryQueue, "__call__", recording)
    state = SimpleGuard(messages, errors)
    yield state
    qInstallMessageHandler(None)


class SimpleGuard:
    def __init__(self, messages: list[str], errors: list[str]) -> None:
        self._messages = messages
        self.errors = errors

    @property
    def messages(self) -> list[str]:
        return [m for m in self._messages if not any(b in m for b in _BENIGN)]

    def assert_clean(self, caplog) -> None:
        assert self.messages == []
        assert self.errors == []
        assert not [r for r in caplog.records if "Dropped UI delivery callback" in r.getMessage()]


def _window(tmp_path: Path, name: str = "prefs"):
    window = make_editor(preferences_path=tmp_path / f"{name}.json")
    pump_qt(30)
    return window


def _project(root: Path, name: str) -> Project:
    project = Project.create(name, root / name)
    from expra_engine.core.component import TransformComponent
    from expra_engine.core.scene import Scene

    scene = Scene("S")
    scene.create_entity("A").add_component(TransformComponent())
    project.save_document(scene, "scenes/a.scene.pb")
    return project


def _wait(condition, timeout: float = 5.0) -> bool:
    return wait_until(lambda: pump_qt(15), condition, timeout=timeout)


def test_background_completion_is_delivered_on_the_ui_thread_to_a_live_widget(
    guard, tmp_path, caplog
) -> None:
    window = _window(tmp_path)
    main_thread = threading.get_ident()
    seen: dict[str, object] = {}

    def work(_cancel, _progress):
        seen["worker"] = threading.get_ident()
        return "payload"

    def on_result(_key, result):
        seen["callback_thread"] = threading.get_ident()
        window._console.log(f"[stress] {result}")  # touches a real widget
        seen["result"] = result

    window._coordinator.run("stress-live", work, on_result=on_result)
    assert _wait(lambda: "result" in seen)
    assert seen["worker"] != main_thread
    assert seen["callback_thread"] == main_thread
    assert "[stress] payload" in window._console.text()
    window._on_close()
    pump_qt(30)
    guard.assert_clean(caplog)


def test_close_while_a_worker_is_active_drops_its_late_result(guard, tmp_path, caplog) -> None:
    window = _window(tmp_path)
    started, release = threading.Event(), threading.Event()
    delivered: list[str] = []

    def work(cancel, _progress):
        started.set()
        release.wait(timeout=10)
        return "late"

    window._coordinator.run(
        "stress-late", work, on_result=lambda _k, r: delivered.append(r), on_error=lambda _k, e: delivered.append(e)
    )
    assert started.wait(5)
    window._on_close()  # worker still running
    release.set()  # result arrives after close
    pump_qt(200)
    assert delivered == []
    assert window._delivery_queue.is_closed
    guard.assert_clean(caplog)


def test_results_arriving_after_close_never_reach_destroyed_widgets(guard, tmp_path, caplog) -> None:
    window = _window(tmp_path)
    console = window._console
    gate = threading.Event()
    calls: list[str] = []

    def work(_cancel, _progress):
        gate.wait(timeout=10)
        return "x"

    def on_result(_key, _result):
        calls.append("called")
        console.log("must never run")  # would raise on a destroyed widget

    window._coordinator.run("stress-destroyed", work, on_result=on_result)
    window._on_close()
    window.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    gate.set()
    pump_qt(200)
    gc.collect()
    assert calls == []
    guard.assert_clean(caplog)


def test_repeated_open_close_with_workers_in_flight(guard, tmp_path, caplog) -> None:
    for index in range(12):
        window = _window(tmp_path, f"prefs{index}")
        release = threading.Event()
        window._coordinator.run(
            f"stress-cycle-{index}",
            lambda _c, _p, gate=release, n=index: gate.wait(timeout=5) or n,
            on_result=lambda _k, _r: None,
        )
        window._assets.refresh()  # a real UI-owned scan in flight as well
        if index % 2:
            window._on_close()
            release.set()
        else:
            release.set()
            pump_qt(20)
            window._on_close()
        pump_qt(15)
    pump_qt(100)
    gc.collect()
    guard.assert_clean(caplog)


def test_repeated_play_stop_cycles(guard, tmp_path, caplog) -> None:
    window = _window(tmp_path)
    try:
        for _ in range(25):
            window._act_play()
            pump_qt(25)
            assert window._engine.run_state == EngineRunState.PLAY
            window._act_stop()
            pump_qt(10)
            assert window._engine.run_state == EngineRunState.EDIT
        assert window._runtime_preview._after_id is None
    finally:
        window._on_close()
        pump_qt(30)
    guard.assert_clean(caplog)


def test_repeated_project_switching_with_scans_in_flight(guard, tmp_path, caplog) -> None:
    projects = [_project(tmp_path, "one"), _project(tmp_path, "two")]
    window = _window(tmp_path)
    try:
        for index in range(24):
            window._project_workflow.open_loaded(Project.load(projects[index % 2].path))
            pump_qt(8)
        pump_qt(300)
        last = Project.load(projects[23 % 2].path).path.resolve()
        assert window._engine.project is not None
        assert window._engine.project.path.resolve() == last
        assert window._assets.root_directory == last
    finally:
        window._on_close()
        pump_qt(30)
    guard.assert_clean(caplog)


def test_flood_from_many_threads_then_close_from_another_thread(guard, caplog) -> None:
    from PySide6.QtWidgets import QWidget

    from expra_engine.editor.qt.delivery import QtDeliveryQueue

    for _ in range(15):
        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []
        main_thread = threading.get_ident()
        wrong_thread: list[int] = []

        def record(
            value: int, delivered=delivered, wrong_thread=wrong_thread, owner=main_thread
        ) -> None:
            if threading.get_ident() != owner:
                wrong_thread.append(value)
            delivered.append(value)

        def flood(offset: int, queue=queue, record=record) -> None:
            for i in range(300):
                queue(lambda v=offset + i: record(v))

        threads = [threading.Thread(target=flood, args=(t * 1000,)) for t in range(8)]
        for thread in threads:
            thread.start()
        pump_qt(20)
        closer = threading.Thread(target=queue.close)  # close from a non-owner thread mid-flood
        closer.start()
        for thread in (*threads, closer):
            thread.join(timeout=5)
        pump_qt(80)
        assert wrong_thread == []
        assert queue.is_closed
        seen = len(delivered)
        pump_qt(60)
        assert len(delivered) == seen, "nothing may be delivered after close"
        widget.deleteLater()
        pump_qt(10)
    guard.assert_clean(caplog)


def test_callback_that_closes_the_queue_from_inside_the_drain(guard, caplog) -> None:
    from PySide6.QtWidgets import QWidget

    from expra_engine.editor.qt.delivery import QtDeliveryQueue

    for _ in range(50):
        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        after: list[int] = []
        queue(queue.close)
        queue(lambda after=after: after.append(1))
        pump_qt(60)
        assert queue.is_closed
        assert after == []
        widget.deleteLater()
    pump_qt(30)
    guard.assert_clean(caplog)
