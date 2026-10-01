"""Tests for QtDeliveryQueue — thread-safe Qt main-thread delivery.

All tests run on the Qt offscreen platform to avoid needing a display.
"""

from __future__ import annotations

import threading
import time

import pytest

from tests.support.qt_app import ensure_qt_app, pump_qt


@pytest.fixture(scope="module")
def qt_app():
    """Module-scoped QApplication — created once, reused across tests."""
    yield ensure_qt_app()


def _drain_events(_app, ms: int = 100) -> None:
    """Process pending Qt events for up to ``ms`` milliseconds."""
    pump_qt(ms)


class TestQtDeliveryQueueBasic:
    def test_enqueue_and_drain_delivers_callback(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []
        queue(lambda: delivered.append(1))
        _drain_events(qt_app, ms=200)
        assert delivered == [1]
        queue.close()
        widget.deleteLater()

    def test_closed_queue_rejects_callbacks(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        queue.close()
        delivered: list[int] = []
        queue(lambda: delivered.append(1))
        _drain_events(qt_app, ms=100)
        assert delivered == []
        widget.deleteLater()

    def test_is_closed_false_initially(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        assert not queue.is_closed
        queue.close()
        widget.deleteLater()

    def test_is_closed_true_after_close(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        queue.close()
        assert queue.is_closed
        widget.deleteLater()

    def test_close_is_idempotent(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        queue.close()
        queue.close()  # must not raise
        assert queue.is_closed
        widget.deleteLater()

    def test_multiple_callbacks_delivered_in_order(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []
        for i in range(5):
            queue(lambda v=i: delivered.append(v))
        _drain_events(qt_app, ms=200)
        assert delivered == [0, 1, 2, 3, 4]
        queue.close()
        widget.deleteLater()

    def test_faulty_callback_does_not_stop_later_callbacks(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []
        queue(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        queue(lambda: delivered.append(42))
        _drain_events(qt_app, ms=200)
        assert delivered == [42]
        queue.close()
        widget.deleteLater()


class TestQtDeliveryQueueThreaded:
    def test_enqueue_from_worker_thread_delivered_on_main(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []

        def worker() -> None:
            for i in range(3):
                queue(lambda v=i: delivered.append(v))

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)
        _drain_events(qt_app, ms=300)
        assert sorted(delivered) == [0, 1, 2]
        queue.close()
        widget.deleteLater()


class TestQtDeliveryThreadOwnership:
    def test_callbacks_run_on_the_main_thread_via_app_coordinator(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.coordinators.app_coordinator import AppCoordinator
        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        coordinator = AppCoordinator(deliver=queue)
        threads: dict[str, int] = {}
        main_ident = threading.get_ident()

        def work(_cancel, _progress) -> int:
            threads["worker"] = threading.get_ident()
            return 7

        def on_result(_key: str, result: int) -> None:
            threads["result"] = threading.get_ident()
            threads["value"] = result

        coordinator.run("thread-ownership", work, on_result=on_result)
        deadline = time.monotonic() + 5
        while "result" not in threads and time.monotonic() < deadline:
            _drain_events(qt_app, ms=30)
        coordinator.shutdown()
        queue.close()
        widget.deleteLater()
        assert threads["value"] == 7
        assert threads["worker"] != main_ident
        assert threads["result"] == main_ident

    def test_close_from_a_worker_thread_drops_pending_and_later_callbacks(self, qt_app) -> None:
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        delivered: list[int] = []
        queue(lambda: delivered.append(1))
        closer = threading.Thread(target=queue.close)
        closer.start()
        closer.join(timeout=2.0)
        queue(lambda: delivered.append(2))
        _drain_events(qt_app, ms=150)
        assert delivered == []
        assert queue.is_closed
        widget.deleteLater()

    def test_destroying_the_widget_closes_the_queue(self, qt_app) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        queue = QtDeliveryQueue(widget)
        widget.deleteLater()
        # processEvents() never runs DeferredDelete events; deliver them explicitly.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        _drain_events(qt_app, ms=100)
        assert queue.is_closed


class TestQtDeliveryQueueBoundedDrain:
    """One drain turn never runs an unbounded backlog; the rest waits for later turns."""

    def _queue(self, qt_app):
        from PySide6.QtWidgets import QWidget

        from expra_engine.editor.qt.delivery import QtDeliveryQueue

        widget = QWidget()
        return QtDeliveryQueue(widget), widget

    def test_callback_enqueued_during_drain_is_delivered_in_the_same_drain(self, qt_app) -> None:
        queue, widget = self._queue(qt_app)
        order: list[str] = []

        def first() -> None:
            order.append("first")
            queue(lambda: order.append("nested"))

        queue(first)
        queue._drain()
        assert order == ["first", "nested"]
        queue.close()
        widget.deleteLater()

    def test_self_replenishing_callbacks_yield_between_drain_turns(self, qt_app) -> None:
        queue, widget = self._queue(qt_app)
        delivered = 0
        total = 500

        def enqueue_next() -> None:
            nonlocal delivered
            delivered += 1
            if delivered < total:
                queue(enqueue_next)

        queue(enqueue_next)
        queue._drain()
        assert 0 < delivered < total, "one turn must not drain an unbounded backlog"
        while delivered < total:
            queue._drain()
        assert delivered == total
        queue.close()
        widget.deleteLater()

    def test_drain_yields_after_the_time_budget(self, qt_app) -> None:
        from unittest.mock import patch

        queue, widget = self._queue(qt_app)
        delivered: list[int] = []
        for index in range(50):
            queue(lambda index=index: delivered.append(index))
        with patch.object(time, "monotonic", side_effect=(0.0, 0.006)):
            queue._drain()
        assert 0 < len(delivered) < 50
        while len(delivered) < 50:
            queue._drain()
        assert delivered == list(range(50))
        queue.close()
        widget.deleteLater()

    def test_app_coordinator_posts_are_delivered_across_bounded_turns(self, qt_app) -> None:
        from expra_engine.coordinators.app_coordinator import AppCoordinator

        queue, widget = self._queue(qt_app)
        coordinator = AppCoordinator(deliver=queue, runner=lambda _worker: None)
        delivered: list[int] = []
        for index in range(250):
            coordinator.post(lambda index=index: delivered.append(index))
        queue._drain()
        assert 0 < len(delivered) < 250
        while len(delivered) < 250:
            queue._drain()
        assert delivered == list(range(250))
        queue.close()
        widget.deleteLater()

    def test_close_from_within_a_callback_stops_the_drain(self, qt_app) -> None:
        queue, widget = self._queue(qt_app)
        ran: list[str] = []

        def stop() -> None:
            ran.append("stop")
            queue.close()

        queue(stop)
        queue(lambda: ran.append("later"))
        queue._drain()
        assert ran == ["stop"]
        assert queue.is_closed
        widget.deleteLater()
