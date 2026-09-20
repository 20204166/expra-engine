"""Stable action registry for UI button and toolbar callbacks.

Adapted from System Analyzer maintenance/ui/action_coordinator.py
(ButtonCoordinator).

BUTTON COORDINATOR OWNS ACTIONS.

Flow:
    UI control -> action request -> ButtonCoordinator
        -> engine/application mutation -> state -> UICoordinator -> Tk presentation
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from expra_engine.observability import ObservabilityWatcher


@dataclass(slots=True)
class _ActionRecord:
    callback: Callable[[], None]
    enabled: bool
    widgets: list[Any] = field(default_factory=list)


class ButtonCoordinator:
    """Register stable action IDs and keep bound widgets in sync.

    In the game editor, action IDs represent editor commands such as:
    ``new_project``, ``open_project``, ``save_project``, ``new_scene``,
    ``save_scene``, ``add_entity``, ``delete_entity``, ``play``, ``pause``,
    ``stop``, ``import_asset``.

    Widgets should not contain engine business logic; they only dispatch
    named actions through this registry.
    """

    def __init__(self, *, observer: ObservabilityWatcher | None = None) -> None:
        self._actions: dict[str, _ActionRecord] = {}
        self._observer = observer

    def register(
        self,
        action_id: str,
        callback: Callable[[], None],
        *,
        enabled: bool = True,
        replace: bool = False,
    ) -> None:
        if not action_id:
            raise ValueError("Action id cannot be empty")
        existing = self._actions.get(action_id)
        if existing is not None and not replace:
            raise ValueError(f"Action already registered: {action_id}")
        widgets = [
            widget
            for widget in (existing.widgets if existing is not None else [])
            if self._apply_state(widget, enabled)
        ]
        self._actions[action_id] = _ActionRecord(
            callback=callback,
            enabled=enabled,
            widgets=widgets,
        )

    def command(self, action_id: str) -> Callable[[], bool]:
        return lambda: self.dispatch(action_id)

    def bind(self, widget: Any, action_id: str) -> None:
        record = self._actions[action_id]
        if not self._widget_exists(widget):
            return
        if widget not in record.widgets:
            record.widgets.append(widget)
        config = self._widget_config(widget)
        if config is not None:
            try:
                config(command=self.command(action_id))
            except TypeError:
                pass
            except (RuntimeError, tk.TclError):
                record.widgets = [item for item in record.widgets if item is not widget]
                return
        if not self._apply_state(widget, record.enabled):
            record.widgets = [item for item in record.widgets if item is not widget]

    def dispatch(self, action_id: str) -> bool:
        record = self._actions.get(action_id)
        if record is None or not record.enabled:
            if self._observer is not None:
                self._observer.record_event(
                    f"ui:action:{action_id}",
                    "rejected",  # type: ignore[arg-type]
                )
            return False
        observer = self._observer
        token = observer.begin(f"ui:action:{action_id}") if observer is not None else None
        try:
            record.callback()
        except Exception as error:
            if observer is not None and token is not None:
                observer.finish(token, outcome="failure", detail=type(error).__name__)
            raise
        else:
            if observer is not None and token is not None:
                observer.finish(token)
        return True

    def set_enabled(self, action_id: str, enabled: bool) -> None:
        record = self._actions[action_id]
        record.enabled = enabled
        record.widgets = [widget for widget in record.widgets if self._apply_state(widget, enabled)]

    def is_enabled(self, action_id: str) -> bool:
        return self._actions[action_id].enabled

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(self._actions)

    def unregister(self, action_id: str) -> None:
        self._actions.pop(action_id, None)

    def clear_prefix(self, prefix: str) -> None:
        for action_id in tuple(self._actions):
            if action_id.startswith(prefix):
                del self._actions[action_id]

    @staticmethod
    def _widget_config(widget: Any) -> Any:
        config = getattr(widget, "config", None)
        if config is None:
            config = getattr(widget, "configure", None)
        return config

    @staticmethod
    def _apply_state(widget: Any, enabled: bool) -> bool:
        if not ButtonCoordinator._widget_exists(widget):
            return False
        state = "normal" if enabled else "disabled"
        config = ButtonCoordinator._widget_config(widget)
        if config is None:
            return True
        try:
            config(state=state)
        except TypeError:
            return True
        except (RuntimeError, tk.TclError):
            return False
        return True

    @staticmethod
    def _widget_exists(widget: Any) -> bool:
        exists = getattr(widget, "winfo_exists", None)
        if exists is None:
            return True
        try:
            return bool(exists())
        except (RuntimeError, tk.TclError):
            return False
