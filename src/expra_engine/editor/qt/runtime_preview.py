"""Qt scheduling adapter for the editor's embedded runtime preview.

Drives the Engine from the Qt event loop with QTimer.singleShot without making the
Engine depend on Qt.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any, Literal

from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.messages import engine as engine_messages
from expra_engine.observability import ObservabilityWatcher

LOGGER = logging.getLogger(__name__)


class QtRuntimePreviewLoop:
    """Drive an Engine from the Qt event loop without making the Engine depend on Qt."""

    def __init__(
        self,
        widget: Any,
        engine: Engine,
        render: Callable[[], None],
        *,
        observer: ObservabilityWatcher | None = None,
        camera_step: Callable[[float], None] | None = None,
        on_world_startup_diagnostic: Callable[[str], None] | None = None,
        on_world_startup_error: Callable[[], None] | None = None,
        on_runtime_error: Callable[[str], None] | None = None,
    ) -> None:
        self._widget = widget
        self._engine = engine
        self._render = render
        self._camera_step = camera_step
        self._timer: Any = None  # QTimer | None
        self._observer = observer
        self._on_world_startup_diagnostic = on_world_startup_diagnostic
        self._on_world_startup_error = on_world_startup_error
        self._on_runtime_error = on_runtime_error
        self._last_world_startup_diagnostic: str | None = None

    # Exposed so tests can inspect it (mirrors RuntimePreviewLoop._after_id)
    @property
    def _after_id(self) -> Any:
        return self._timer

    def start(self) -> None:
        self.stop()
        self._last_world_startup_diagnostic = None
        if not self._widget_exists():
            self._stop_engine()
            return
        self._schedule_tick(16)

    def stop(self) -> None:
        if self._timer is not None:
            with contextlib.suppress(RuntimeError):
                self._timer.stop()
            self._timer = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule_tick(self, delay_ms: int) -> None:
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self._tick)
        self._timer = timer
        timer.start(delay_ms)

    def _tick(self) -> None:
        self._timer = None
        if not self._widget_exists():
            self._stop_engine()
            return
        if self._engine.run_state == EngineRunState.PLAY:
            observer = self._observer
            token = observer.begin("editor:preview:tick") if observer is not None else None
            outcome: Literal["success", "failure"] = "success"
            try:
                dt = self._engine.tick()
                if self._camera_step is not None:
                    self._camera_step(dt)
                if self._report_world_startup_state():
                    return
                self._render()
            except Exception as exc:  # noqa: BLE001
                outcome = "failure"
                self._stop_engine()
                message = engine_messages.runtime_preview_tick_failed(
                    type(exc).__name__, str(exc)
                )
                if self._on_runtime_error is None:
                    LOGGER.error("%s", message)
                else:
                    try:
                        self._on_runtime_error(message)
                    except Exception as report_error:  # noqa: BLE001
                        LOGGER.error("Runtime preview error reporting failed: %s", report_error)
                return
            finally:
                if observer is not None and token is not None:
                    observer.finish(token, outcome=outcome)
        if (
            self._engine.run_state in (EngineRunState.PLAY, EngineRunState.PAUSED)
            and self._widget_exists()
        ):
            self._schedule_tick(16)

    def _report_world_startup_state(self) -> bool:
        world_system = getattr(self._engine, "world_streaming_system", None)
        if world_system is None:
            self._last_world_startup_diagnostic = None
            return False
        diagnostic = getattr(world_system, "startup_diagnostic", None)
        if diagnostic is not None and diagnostic != self._last_world_startup_diagnostic:
            callback = self._on_world_startup_diagnostic
            if callback is not None:
                callback(diagnostic)
        self._last_world_startup_diagnostic = diagnostic
        if getattr(world_system, "startup_error", None) is None:
            return False
        callback = self._on_world_startup_error
        if callback is None:
            self._stop_engine()
        else:
            callback()
        return True

    def _stop_engine(self) -> None:
        observer = self._observer
        try:
            stopped = bool(self._engine.stop())
        except Exception:  # noqa: BLE001
            if observer is not None:
                observer.record_event("editor:preview:fail_closed", "failure")
            return
        if observer is not None and stopped:
            observer.increment("editor:preview:fail_closed", "stopped")

    def _widget_exists(self) -> bool:
        widget = self._widget
        if widget is None:
            return False
        # QWidget.isVisible() might return False for hidden widgets, so check
        # that the C++ object hasn't been deleted using a try/except.
        try:
            # PySide6 raises RuntimeError: "Internal C++ object … already deleted."
            widget.objectName()
            return True
        except RuntimeError:
            return False


__all__ = ["QtRuntimePreviewLoop"]
