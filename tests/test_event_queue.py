"""Tests for runtime EventQueue — signal/publish dispatch.

Edge cases derived from ppb/engine.py semantics (PursuedPyBear,
Artistic License 2.0), translated to Expra's EventQueue API.

Tests cover:
  - basic signal → publish
  - FIFO ordering
  - handler naming (camel_to_snake)
  - targeted delivery (only specific objects)
  - broadcast traversal (walk)
  - events signalled inside handlers are deferred (queued, not immediate)
  - invalid handler signature raises BadEventHandlerException
  - flush discards all pending
  - drain publishes all pending
  - empty queue is safe
"""

import unittest
from dataclasses import dataclass
from typing import Any, ClassVar

from expra_engine.core.errors import BadEventHandlerException
from expra_engine.runtime.event_queue import EventQueue, walk


@dataclass
class Ping:
    value: int = 0


@dataclass
class Pong:
    value: int = 0


class _Root:
    """Simple tree root with a children list."""

    def __init__(self) -> None:
        self.children: list[Any] = []
        self.received: list[Any] = []

    def on_ping(self, event: Ping, signal: Any) -> None:
        self.received.append(event)


class _Child:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def on_pong(self, event: Pong, signal: Any) -> None:
        self.received.append(event)


class TestEventQueueBasic(unittest.TestCase):
    def _make(self, root: Any | None = None) -> EventQueue:
        return EventQueue(root or _Root())

    def test_pending_false_when_empty(self) -> None:
        eq = self._make()
        self.assertFalse(eq.pending)

    def test_pending_true_after_signal(self) -> None:
        eq = self._make()
        eq.signal(Ping())
        self.assertTrue(eq.pending)

    def test_pending_false_after_publish(self) -> None:
        eq = self._make()
        eq.signal(Ping())
        eq.publish()
        self.assertFalse(eq.pending)

    def test_publish_on_empty_queue_is_safe(self) -> None:
        eq = self._make()
        eq.publish()  # must not raise

    def test_flush_clears_all(self) -> None:
        eq = self._make()
        for _ in range(5):
            eq.signal(Ping())
        eq.flush()
        self.assertFalse(eq.pending)

    def test_drain_publishes_all(self) -> None:
        root = _Root()
        eq = EventQueue(root)
        eq.signal(Ping(1))
        eq.signal(Ping(2))
        eq.drain()
        self.assertFalse(eq.pending)
        self.assertEqual(len(root.received), 2)


class TestEventQueueOrdering(unittest.TestCase):
    """Events are delivered in FIFO order."""

    def test_fifo_order(self) -> None:
        log: list[int] = []

        class Recorder:
            def on_ping(self, event: Ping, signal: Any) -> None:
                log.append(event.value)

        root = Recorder()
        eq = EventQueue(root)
        eq.signal(Ping(1))
        eq.signal(Ping(2))
        eq.signal(Ping(3))
        eq.drain()
        self.assertEqual(log, [1, 2, 3])


class TestEventQueueHandlerNaming(unittest.TestCase):
    """Handler names derive from class name via camel_to_snake."""

    def test_pong_handler_called(self) -> None:
        child = _Child()
        root = _Root()
        root.children.append(child)
        eq = EventQueue(root)
        eq.signal(Pong(42))
        eq.drain()
        self.assertEqual(len(child.received), 1)
        self.assertEqual(child.received[0].value, 42)

    def test_unknown_handler_is_ignored(self) -> None:
        class Silent:
            pass

        root = Silent()
        eq = EventQueue(root)
        eq.signal(Ping())
        eq.drain()  # must not raise


class TestEventQueueTargeted(unittest.TestCase):
    """Targeted events reach only specified objects."""

    def test_targeted_reaches_target(self) -> None:
        target = _Root()
        _Root()
        eq = EventQueue(target)
        eq.signal(Ping(99), targets=[target])
        eq.drain()
        self.assertEqual(len(target.received), 1)
        self.assertEqual(target.received[0].value, 99)

    def test_targeted_does_not_reach_non_target(self) -> None:
        target = _Root()
        other = _Root()
        eq = EventQueue(object())  # root not in delivery
        eq.signal(Ping(7), targets=[target])
        eq.drain()
        self.assertEqual(len(other.received), 0)

    def test_targeted_empty_list(self) -> None:
        eq = EventQueue(object())
        eq.signal(Ping(), targets=[])
        eq.drain()  # must not raise


class TestEventQueueDeferredSignal(unittest.TestCase):
    """Events signalled inside a handler are deferred, not immediate."""

    def test_signalled_during_handler_processed_after_current(self) -> None:
        order: list[str] = []

        @dataclass
        class A:
            pass

        @dataclass
        class B:
            pass

        class Root:
            def on_a(self, event: A, signal: Any) -> None:
                order.append("a")
                signal(B())  # should come after all pending A's

            def on_b(self, event: B, signal: Any) -> None:
                order.append("b")

        root = Root()
        eq = EventQueue(root)
        eq.signal(A())
        eq.drain()
        self.assertEqual(order, ["a", "b"])


class TestEventQueueBadHandler(unittest.TestCase):
    """Invalid handler signatures raise BadEventHandlerException."""

    def test_bad_signature_raises(self) -> None:
        class Broken:
            def on_ping(self, event: Ping) -> None:  # missing signal arg
                pass

        root = Broken()
        eq = EventQueue(root)
        eq.signal(Ping())
        with self.assertRaises(BadEventHandlerException):
            eq.publish()


class TestWalk(unittest.TestCase):
    """walk() traverses the object tree breadth-first."""

    def test_root_only(self) -> None:
        root = object()
        result = list(walk(root))
        self.assertEqual(result, [root])

    def test_root_with_children(self) -> None:
        child1 = object()
        child2 = object()

        class Root:
            children: ClassVar = [child1, child2]

        root = Root()
        result = list(walk(root))
        self.assertIn(root, result)
        self.assertIn(child1, result)
        self.assertIn(child2, result)

    def test_nested_children(self) -> None:
        grandchild = object()

        class Child:
            children: ClassVar = [grandchild]

        class Root:
            children: ClassVar = [Child()]

        root = Root()
        result = list(walk(root))
        self.assertIn(grandchild, result)

    def test_entities_attr_also_traversed(self) -> None:
        """walk() uses _entities fallback for Expra Scene objects."""
        entity = object()

        class FakeScene:
            _entities: ClassVar = [entity]

        scene = FakeScene()
        result = list(walk(scene))
        self.assertIn(entity, result)


if __name__ == "__main__":
    unittest.main()
