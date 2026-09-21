"""Runtime event queue — signal/publish dispatch.

Architecturally adapted from ppb/engine.py GameEngine (PursuedPyBear,
Artistic License 2.0). Key preserved semantics:
  - Queued delivery (not immediate/synchronous)
  - Deterministic FIFO ordering
  - Handler names derived by camel_to_snake
  - Optional targeted delivery (specific objects only)
  - Handler-signature validation with helpful error messages
  - Events signalled inside handlers are delivered after the current one

Expra-specific differences from PPB:
  - EventQueue is a standalone object; not mixed into the Engine class
  - No EngineChildren / scene-stack coupling (that lives in Engine)
  - No event_extensions (hydration callbacks); not needed yet
  - Targets use a plain list (not WeakSet) for simplicity and debuggability
  - ``walk(root)`` is a module-level utility for traversal

``signal`` and ``publish`` are the two primitive operations. Everything
else is convenience.
"""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from expra_engine.core.errors import BadEventHandlerException
from expra_engine.core.utils import camel_to_snake
from expra_engine.runtime.events import FrameUpdate, Update
from expra_engine.runtime.input import ActionEvent

__all__ = ("EventQueue", "walk")

Signal = Callable[[Any], None]

_handler_cache: dict[str, str] = {}


def _handler_name(event_class_name: str) -> str:
    cached = _handler_cache.get(event_class_name)
    if cached is None:
        cached = "on_" + camel_to_snake(event_class_name)
        _handler_cache[event_class_name] = cached
    return cached


def walk(root: Any) -> Iterable[Any]:
    """Breadth-first traversal of a game-object tree.

    Yields root, then all objects reachable via a ``children`` attribute.
    Works with Expra Scene (entities list) and future hierarchy objects.

    Adapted from ppb/gomlib.py walk() (PursuedPyBear, Artistic License 2.0).
    """
    q: deque[Any] = deque([root])
    while q:
        cur = q.popleft()
        yield cur
        children = getattr(cur, "children", None) or getattr(cur, "_entities", None)
        if children is not None:
            with contextlib.suppress(TypeError):
                q.extend(children)


class _TargetedEvent:
    """Wraps an event with an explicit delivery target list."""

    __slots__ = ("event", "targets")

    def __init__(self, event: Any, targets: Iterable[Any]) -> None:
        self.event = event
        self.targets = list(targets)


class EventQueue:
    """FIFO event queue with handler-based dispatch.

    Usage::

        eq = EventQueue(root_object)
        eq.signal(Update(0.016))
        while eq.pending:
            eq.publish()

    ``root_object`` is the traversal root for broadcast events (normally
    the active scene or a container that owns all runtime objects).
    """

    def __init__(self, root: Any) -> None:
        self._root = root
        self._queue: deque[Any] = deque()

    @property
    def pending(self) -> bool:
        """True if there are events waiting to be published."""
        return bool(self._queue)

    def signal(self, event: Any, *, targets: Iterable[Any] | None = None) -> None:
        """Enqueue an event.

        Thread-safe (deque.append is atomic in CPython).

        :param event: Any event instance (typically a dataclass).
        :param targets: If given, only these objects receive the event.
        """
        if targets is not None:
            self._queue.append(_TargetedEvent(event, targets))
        else:
            self._queue.append(event)

    def publish(self) -> None:
        """Dequeue and dispatch the next event to all appropriate handlers.

        Handler names are derived from the event class name via
        ``camel_to_snake``: ``Update`` → ``on_update``.
        """
        if not self._queue:
            return

        item = self._queue.popleft()
        if isinstance(item, _TargetedEvent):
            event = item.event
            targets: Iterable[Any] = item.targets
        else:
            event = item
            targets = walk(self._root)

        handler_name = _handler_name(type(event).__name__)
        for obj in targets:
            method = getattr(obj, handler_name, None)
            if method is not None and callable(method):
                try:
                    handled = method(event, self.signal)
                except TypeError as exc:
                    from inspect import signature

                    sig = signature(method)
                    try:
                        sig.bind(event, self.signal)
                    except TypeError:
                        raise BadEventHandlerException(obj, handler_name, event) from exc
                    raise
                if isinstance(event, ActionEvent) and handled:
                    break
            elif isinstance(event, (ActionEvent, FrameUpdate, Update)):
                continue
            if isinstance(event, (ActionEvent, FrameUpdate, Update)):
                continue
            behaviours = getattr(obj, "behaviours", ())
            for behaviour in tuple(behaviours):
                if not getattr(obj, "enabled", True) or not getattr(behaviour, "enabled", True):
                    continue
                callback = getattr(behaviour, handler_name, None)
                if callback is None or not callable(callback):
                    continue
                from inspect import signature

                callback_signature = signature(callback)
                try:
                    callback_signature.bind(event, self.signal)
                except TypeError:
                    try:
                        callback_signature.bind(event)
                    except TypeError as invalid_signature:
                        raise BadEventHandlerException(
                            behaviour, handler_name, event
                        ) from invalid_signature
                    callback(event)
                else:
                    callback(event, self.signal)
        if isinstance(event, Update):
            callback = getattr(self._root, "on_update_complete", None)
            if callable(callback):
                callback(event)

    def flush(self) -> None:
        """Discard all pending events.

        Called before scene transitions to prevent stale events being
        delivered to the wrong scene (same invariant as PPB).
        """
        self._queue.clear()

    def drain(self) -> None:
        """Publish all pending events in order."""
        while self._queue:
            self.publish()

    def set_root(self, root: Any) -> None:
        """Update the traversal root (e.g. after a scene change)."""
        self._root = root
