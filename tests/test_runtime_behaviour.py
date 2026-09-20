"""Tests for the standalone runtime behaviour contract."""

import unittest
from collections.abc import Callable

from expra_engine.core.engine import Engine
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Scene
from expra_engine.runtime import Behaviour, BehaviourFactory
from expra_engine.runtime.events import Update
from expra_engine.runtime.input import ActionEvent, ActionId, PhysicalInput


class RecordingBehaviour(Behaviour):
    """Minimal concrete behaviour used to verify callback signatures."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def on_attach(self, entity: object) -> None:
        self.calls.append("attach")

    def on_start(self) -> None:
        self.calls.append("start")

    def on_update(self, event: Update, signal: object) -> None:
        self.calls.append("update")

    def on_input(self, event: ActionEvent, signal: object) -> bool:
        self.calls.append("input")
        return True

    def on_stop(self) -> None:
        self.calls.append("stop")

    def on_detach(self) -> None:
        self.calls.append("detach")


class LifecycleBehaviour(Behaviour):
    """Behaviour double that records lifecycle callbacks and entity IDs."""

    def __init__(self, log: list[tuple[Behaviour, str, str | None]]) -> None:
        super().__init__()
        self.log = log

    def _record(self, callback: str, entity_id: str | None = None) -> None:
        current_entity_id = entity_id
        if current_entity_id is None and self.entity is not None:
            current_entity_id = self.entity.entity_id
        self.log.append((self, callback, current_entity_id))

    def on_attach(self, entity: Entity) -> None:
        self._record("attach", entity.entity_id)

    def on_start(self) -> None:
        self._record("start")

    def on_update(self, event: Update, signal: object) -> None:
        self._record("update")

    def on_stop(self) -> None:
        self._record("stop")

    def on_detach(self) -> None:
        self._record("detach")


def lifecycle_factory(
    log: list[tuple[Behaviour, str, str | None]],
) -> Callable[[], LifecycleBehaviour]:
    """Return an explicit factory that creates a fresh lifecycle double."""
    return lambda: LifecycleBehaviour(log)


class DispatchBehaviour(Behaviour):
    """Behaviour double for runtime event traversal tests."""

    def __init__(
        self,
        label: str,
        log: list[str],
        *,
        remove_label: str | None = None,
        error: BaseException | None = None,
        consume_input: bool = False,
    ) -> None:
        super().__init__()
        self.label = label
        self.log = log
        self.remove_label = remove_label
        self.error = error
        self.consume_input = consume_input

    def on_update(self, event: Update, signal: object) -> None:
        if self.error is not None:
            raise self.error
        self.log.append(self.label)
        if self.remove_label is not None and self.entity is not None:
            target = next(
                behaviour
                for behaviour in self.entity.behaviours
                if getattr(behaviour, "label", None) == self.remove_label
            )
            self.entity.remove_behaviour(target)

    def on_input(self, event: ActionEvent, signal: object) -> bool:
        self.log.append(f"{self.label}:{event.phase}")
        return self.consume_input


class EventBehaviour(Behaviour):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    def on_player_damaged(self, event: object) -> None:
        self.log.append("damaged")


def dispatch_factory(
    label: str,
    log: list[str],
    *,
    remove_label: str | None = None,
    error: BaseException | None = None,
    consume_input: bool = False,
) -> Callable[[], DispatchBehaviour]:
    return lambda: DispatchBehaviour(
        label,
        log,
        remove_label=remove_label,
        error=error,
        consume_input=consume_input,
    )


def _runtime_engine(scene: Scene) -> Engine:
    engine = Engine()
    engine.set_scene(scene)
    engine.play()
    return engine


class TestRuntimeBehaviour(unittest.TestCase):
    def test_new_behaviour_has_no_owner_and_is_enabled(self) -> None:
        behaviour = Behaviour()

        self.assertIsNone(behaviour.entity)
        self.assertTrue(behaviour.enabled)

    def test_default_callbacks_are_no_ops(self) -> None:
        behaviour = Behaviour()
        action = ActionEvent(
            ActionId("jump"),
            "pressed",
            PhysicalInput("keyboard", "space"),
        )

        behaviour.on_attach(object())  # type: ignore[arg-type]
        behaviour.on_start()
        behaviour.on_update(Update(0.016), lambda _: None)
        behaviour.on_stop()
        behaviour.on_detach()

        self.assertFalse(behaviour.on_input(action, lambda _: None))

    def test_subclass_callbacks_can_record_the_runtime_contract(self) -> None:
        behaviour = RecordingBehaviour()
        action = ActionEvent(
            ActionId("jump"),
            "pressed",
            PhysicalInput("keyboard", "space"),
        )

        behaviour.on_attach(object())  # type: ignore[arg-type]
        behaviour.on_start()
        behaviour.on_update(Update(0.016), object())
        self.assertTrue(behaviour.on_input(action, object()))
        behaviour.on_stop()
        behaviour.on_detach()

        self.assertEqual(behaviour.calls, ["attach", "start", "update", "input", "stop", "detach"])

    def test_behaviour_factory_is_callable_type_alias(self) -> None:
        factory: BehaviourFactory = RecordingBehaviour

        self.assertIsInstance(factory(), RecordingBehaviour)


class TestRuntimeBehaviourDispatch(unittest.TestCase):
    def test_named_runtime_events_route_to_behaviour_without_second_queue(self) -> None:
        class PlayerDamaged:
            pass

        log: list[str] = []
        scene = Scene("Events")
        entity = scene.create_entity("Actor")
        entity.add_behaviour(EventBehaviour(log), runtime_factory=lambda: EventBehaviour(log))
        engine = _runtime_engine(scene)
        engine._eq.signal(PlayerDamaged())  # type: ignore[union-attr]
        engine._eq.drain()  # type: ignore[union-attr]
        self.assertEqual(log, ["damaged"])

    def test_input_dispatches_phases_until_consumed(self) -> None:
        log: list[str] = []
        scene = Scene("Input")
        entity = scene.create_entity("Actor")
        entity.add_behaviour(
            DispatchBehaviour("continue", log),
            runtime_factory=dispatch_factory("continue", log),
        )
        entity.add_behaviour(
            DispatchBehaviour("consume", log, consume_input=True),
            runtime_factory=dispatch_factory("consume", log, consume_input=True),
        )
        entity.add_behaviour(
            DispatchBehaviour("unreached", log),
            runtime_factory=dispatch_factory("unreached", log),
        )
        engine = _runtime_engine(scene)
        action = ActionEvent(
            ActionId("jump"),
            "pressed",
            PhysicalInput("keyboard", "space"),
        )
        release = ActionEvent(action.action, "released", action.physical)

        engine._eq.signal(action)  # type: ignore[union-attr]
        engine._eq.signal(release)  # type: ignore[union-attr]
        engine._eq.drain()  # type: ignore[union-attr]

        self.assertEqual(
            log,
            [
                "continue:pressed",
                "consume:pressed",
                "continue:released",
                "consume:released",
            ],
        )

    def test_update_dispatches_in_entity_and_attachment_order_with_filtering(self) -> None:
        log: list[str] = []
        scene = Scene("Dispatch")
        first = scene.create_entity("First")
        second = scene.create_entity("Second")
        third = scene.create_entity("Third", enabled=False)
        first.add_behaviour(
            DispatchBehaviour("first-a", log),
            runtime_factory=dispatch_factory("first-a", log),
        )
        first.add_behaviour(
            DispatchBehaviour("first-b", log),
            runtime_factory=dispatch_factory("first-b", log),
        )
        second.add_behaviour(
            DispatchBehaviour("second-a", log),
            runtime_factory=dispatch_factory("second-a", log),
        )
        second.add_behaviour(
            DispatchBehaviour("second-b", log),
            runtime_factory=dispatch_factory("second-b", log),
        )
        third.add_behaviour(
            DispatchBehaviour("third", log),
            runtime_factory=dispatch_factory("third", log),
        )
        engine = _runtime_engine(scene)
        runtime_first = engine.active_scene.find_entity(first.entity_id)  # type: ignore[union-attr]
        assert runtime_first is not None
        runtime_second = engine.active_scene.find_entity(second.entity_id)  # type: ignore[union-attr]
        assert runtime_second is not None
        runtime_second.behaviours[1].enabled = False

        engine._eq.signal(Update(0.016))  # type: ignore[union-attr]
        engine._eq.drain()  # type: ignore[union-attr]

        self.assertEqual(log, ["first-a", "first-b", "second-a"])

    def test_removing_next_behaviour_during_update_does_not_skip_unrelated_behaviour(self) -> None:
        log: list[str] = []
        scene = Scene("Mutation")
        entity = scene.create_entity("Actor")
        entity.add_behaviour(
            DispatchBehaviour("first", log, remove_label="second"),
            runtime_factory=dispatch_factory("first", log, remove_label="second"),
        )
        entity.add_behaviour(
            DispatchBehaviour("second", log),
            runtime_factory=dispatch_factory("second", log),
        )
        entity.add_behaviour(
            DispatchBehaviour("third", log),
            runtime_factory=dispatch_factory("third", log),
        )
        engine = _runtime_engine(scene)

        engine._eq.signal(Update(0.016))  # type: ignore[union-attr]
        engine._eq.drain()  # type: ignore[union-attr]

        self.assertEqual(log, ["first", "third"])

    def test_update_callback_exception_propagates_unchanged(self) -> None:
        error = RuntimeError("sentinel")
        log: list[str] = []
        scene = Scene("Failure")
        entity = scene.create_entity("Actor")
        entity.add_behaviour(
            DispatchBehaviour("failure", log, error=error),
            runtime_factory=dispatch_factory("failure", log, error=error),
        )
        engine = _runtime_engine(scene)

        engine._eq.signal(Update(0.016))  # type: ignore[union-attr]
        with self.assertRaises(RuntimeError) as raised:
            engine._eq.drain()  # type: ignore[union-attr]

        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
