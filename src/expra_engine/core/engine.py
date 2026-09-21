"""Engine — runtime and editor state owner.

ENGINE OWNS GAME STATE.

The Engine holds:
- EngineRunState (EDIT / PLAY / PAUSED)
- the active Project
- the active Scene
- runtime scene stack (for push/pop/replace during PLAY)
- runtime event queue
- runtime systems registry

The editor presents and edits that state through the coordinator boundary.
The engine never owns widgets or Tk resources.

Runtime event system adapted from ppb/engine.py GameEngine
(PursuedPyBear, Artistic License 2.0). Key preserved semantics:
  - EventQueue owns signal/publish
  - scene transitions flush the queue first to prevent stale delivery
  - loop_once / tick API enables Tk-embedding and standalone runner
  - RuntimeSystems start/stop with PLAY transitions
"""

from __future__ import annotations

import contextlib
import json
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from expra_engine.core.scene import Scene
from expra_engine.core.utils import get_time
from expra_engine.runtime.behaviour import Behaviour, BehaviourFactory
from expra_engine.runtime.input import ActionId, InputMap, PhysicalInput
from expra_engine.runtime.transform_interpolation import TransformInterpolator

if TYPE_CHECKING:
    from expra_engine.core.project import Project
    from expra_engine.runtime.behaviour_system import BehaviourSystem
    from expra_engine.runtime.clock import RuntimeClock
    from expra_engine.runtime.event_queue import EventQueue
    from expra_engine.runtime.system import RuntimeSystem


class EngineRunState(Enum):
    """Editor / play state machine."""

    EDIT = "edit"
    PLAY = "play"
    PAUSED = "paused"


class Engine:
    """Central owner of game/editor state.

    Play/pause/stop transition the run state. A temporary runtime scene
    copy is made on Play so Stop can restore the original edit scene.

    The engine does NOT block any thread. Time advancement is driven by
    the caller via ``tick(dt)`` (or the legacy ``update(dt)`` shim).

    Runtime event dispatch
    ----------------------
    While in PLAY state the engine owns an EventQueue rooted at the
    active scene. Call ``tick()`` once per frame; it:
      1. Signals an Idle event with wall-clock dt
      2. Drains all pending events (Idle → RuntimeClock → Update → ...)

    Scene stack
    -----------
    During PLAY the engine maintains a stack of runtime scenes. The
    editor's edit scene is never on the stack; it is preserved across
    all runtime transitions and restored on stop().
    """

    def __init__(self) -> None:
        self._state = EngineRunState.EDIT
        self._project: Project | None = None
        self._edit_scene: Scene | None = None
        self._runtime_scene: Scene | None = None
        self._last_update: float | None = None

        # Runtime scene stack (runtime-only; edit scene never appears here)
        self._scene_stack: list[Scene] = []

        # Runtime event queue (created on play(), destroyed on stop())
        self._eq: EventQueue | None = None  # type: ignore[name-defined]

        # Fixed-step clock
        self._clock: RuntimeClock | None = None  # type: ignore[name-defined]
        self._transform_interpolator = TransformInterpolator()

        # Pluggable runtime systems
        self._systems: list[RuntimeSystem] = []
        self._behaviour_system: BehaviourSystem | None = None
        self._input_map = InputMap()
        self._quit_requested = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def run_state(self) -> EngineRunState:
        return self._state

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def active_scene(self) -> Scene | None:
        """The scene currently visible in the editor or running at runtime.

        During PLAY/PAUSED this is the topmost scene on the runtime stack.
        """
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return self._scene_stack[-1] if self._scene_stack else self._runtime_scene
        return self._edit_scene

    @property
    def edit_scene(self) -> Scene | None:
        return self._edit_scene

    @property
    def input_map(self) -> InputMap:
        return self._input_map

    @property
    def transform_interpolator(self) -> TransformInterpolator:
        """Runtime-only fixed-tick transform snapshots for presentation."""
        return self._transform_interpolator

    @property
    def interpolation_fraction(self) -> float:
        """Return the active clock's render interpolation fraction."""
        return self._clock.interpolation_fraction if self._clock is not None else 0.0

    @property
    def behaviour_system(self) -> BehaviourSystem:
        if self._behaviour_system is None:
            from expra_engine.runtime.behaviour_system import BehaviourSystem
            from expra_engine.runtime.script_registry import ScriptRegistry

            self._behaviour_system = BehaviourSystem(
                ScriptRegistry(self._project.path if self._project else Path.cwd())
            )
            self.add_system(self._behaviour_system)
        return self._behaviour_system

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._input_map.clear()
        if project is not None:
            for action, physical in project.input_settings.items():
                device, control = physical.split(":", 1)
                self._input_map.bind(ActionId(action), PhysicalInput(device, control))
        if self._behaviour_system is not None and hasattr(
            self._behaviour_system.registry, "project_root"
        ):
            self._behaviour_system.registry.project_root = (
                project.path.resolve() if project is not None else Path.cwd()
            )

    def set_script_registry(self, registry: object) -> None:
        from expra_engine.runtime.behaviour_system import BehaviourSystem

        if not hasattr(registry, "resolve"):
            raise TypeError("registry must provide resolve()")
        if self._behaviour_system is not None:
            if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
                self._behaviour_system.stop()
            self.remove_system(self._behaviour_system)  # type: ignore[arg-type]
        self._behaviour_system = BehaviourSystem(registry)  # type: ignore[arg-type]
        self.add_system(self._behaviour_system)
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            self._behaviour_system.start(self)

    def set_scene(self, scene: Scene | None) -> None:
        """Set the scene for editing. Resets any running play state first."""
        if self._state != EngineRunState.EDIT:
            self.stop()
        self._edit_scene = scene
        if self._project is not None and scene is not None:
            self._project.set_active_scene(scene)

    def add_system(self, system: RuntimeSystem) -> None:
        """Register a RuntimeSystem that will receive events during PLAY."""
        self._systems.append(system)

    def remove_system(self, system: RuntimeSystem) -> None:
        """Deregister a RuntimeSystem."""
        with contextlib.suppress(ValueError):
            self._systems.remove(system)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def play(self) -> bool:
        """Enter PLAY state. Returns True if state changed."""
        if self._state == EngineRunState.EDIT:
            behaviour_factories = self._capture_behaviour_factories()
            runtime_scene = self._copy_scene(self._edit_scene)
            self._attach_runtime_behaviours(runtime_scene, behaviour_factories)
            self._runtime_scene = runtime_scene
            self._state = EngineRunState.PLAY
            self._quit_requested = False
            self._last_update = time.monotonic()
            try:
                self._start_runtime()
            except Exception:
                with contextlib.suppress(Exception):
                    self._stop_runtime()
                self._runtime_scene = None
                self._scene_stack.clear()
                self._state = EngineRunState.EDIT
                self._last_update = None
                raise
            return True
        if self._state == EngineRunState.PAUSED:
            self._state = EngineRunState.PLAY
            if self._clock is not None:
                self._clock.resume()
            self._transform_interpolator.reset_history()
            self._last_update = time.monotonic()
            return True
        return False

    def pause(self) -> bool:
        """Enter PAUSED state. Returns True if state changed."""
        if self._state == EngineRunState.PLAY:
            self._state = EngineRunState.PAUSED
            if self._clock is not None:
                self._clock.pause()
            self._transform_interpolator.reset_history()
            return True
        return False

    def stop(self) -> bool:
        """Return to EDIT state, restoring the original edit scene. Returns True if changed."""
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            self._stop_runtime()
            self._runtime_scene = None
            self._scene_stack.clear()
            self._state = EngineRunState.EDIT
            self._last_update = None
            self._quit_requested = False
            return True
        return False

    # ------------------------------------------------------------------
    # Update / tick
    # ------------------------------------------------------------------

    def update(self, dt: float | None = None) -> float:
        """Advance the runtime by ``dt`` seconds (defaults to wall-clock elapsed).

        Legacy shim: only updates timing, does not dispatch events.
        Prefer ``tick()`` for full event-driven updates.

        Returns the elapsed dt used.
        """
        now = time.monotonic()
        if self._state != EngineRunState.PLAY:
            self._last_update = None
            return 0.0

        if dt is None:
            dt = 0.0 if self._last_update is None else now - self._last_update
        self._last_update = now
        return dt

    def tick(self, dt: float | None = None) -> float:
        """Step the runtime by ``dt`` seconds; dispatch all pending events.

        This is the primary game-loop driver. It:
          1. Computes wall-clock dt if not provided.
          2. Signals an Idle event.
          3. Drains all pending events (Idle → clock → Update → ...).
          4. Returns the dt used.

        Safe to call in PAUSED or EDIT state (returns 0.0 immediately).

        Designed for external-loop embedding::

            # In Tk .after() callback:
            dt = engine.tick()
            root.after(16, game_loop)

        Inspired by ppb/engine.py loop_once() (PursuedPyBear, Artistic
        License 2.0).
        """
        if self._state != EngineRunState.PLAY:
            return 0.0

        now = get_time()
        if dt is None:
            dt = 0.0 if self._last_update is None else now - self._last_update
        self._last_update = now

        if self._eq is not None:
            from expra_engine.runtime.events import FrameUpdate, Idle

            self._eq.signal(FrameUpdate(dt))
            self._eq.signal(Idle(dt))
            self._eq.drain()

            if self._quit_requested:
                self.stop()
            else:
                self._transform_interpolator.prune_scene(self.active_scene)

        return dt

    def signal(self, event: object) -> None:
        """Queue a runtime event for the next dispatch pass."""
        if self._eq is None:
            raise RuntimeError("engine is not running")
        self._eq.signal(event)

    # ------------------------------------------------------------------
    # Runtime request events
    # ------------------------------------------------------------------

    def on_quit(self, event: object, signal: object) -> None:
        """Handle a queued ``Quit`` request after the current dispatch pass."""
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            self._quit_requested = True

    def on_action_event(self, event: object, signal: object) -> bool:
        """Handle the conventional semantic quit action before Behaviours."""
        from expra_engine.runtime.input import ActionEvent

        if (
            isinstance(event, ActionEvent)
            and event.phase == "pressed"
            and event.action.value == "quit"
        ):
            self._quit_requested = True
            return True
        return False

    def on_start_scene(self, event: object, signal: object) -> None:
        """Handle a queued request by pushing its materialized scene."""
        if self._state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return
        from expra_engine.runtime.events import StartScene

        if isinstance(event, StartScene):
            self.push_scene(self._materialize_scene(event.new_scene, event.kwargs))

    def on_stop_scene(self, event: object, signal: object) -> None:
        """Handle a queued request by popping the active runtime scene."""
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            from expra_engine.runtime.events import StopScene

            if isinstance(event, StopScene):
                self.pop_scene()

    def on_replace_scene(self, event: object, signal: object) -> None:
        """Handle a queued request by replacing the active runtime scene."""
        if self._state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return
        from expra_engine.runtime.events import ReplaceScene

        if isinstance(event, ReplaceScene):
            self.replace_scene(self._materialize_scene(event.new_scene, event.kwargs))

    def loop_once(self, dt: float | None = None) -> float:
        """Alias for tick(). PPB-style naming for external loop integration."""
        return self.tick(dt)

    # ------------------------------------------------------------------
    # Runtime scene stack (during PLAY only)
    # ------------------------------------------------------------------

    def push_scene(self, scene: Scene) -> None:
        """Push a new scene onto the runtime stack; pause the current scene.

        Only valid during PLAY/PAUSED state. Flushes the event queue
        before the transition (same invariant as PPB) to prevent stale
        events reaching the new scene.

        Signals ScenePaused (to current), then SceneStarted (to new).
        """
        if self._state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            raise RuntimeError("push_scene requires PLAY or PAUSED state")

        if self._eq:
            from expra_engine.runtime.events import ScenePaused, SceneStarted

            self._eq.flush()
            self._eq.signal(ScenePaused())
            self._eq.drain()

        self._scene_stack.append(scene)
        if self._eq:
            self._eq.set_root(self._build_dispatch_root())
            self._eq.signal(SceneStarted())
            try:
                self._eq.drain()
            except Exception:
                self._scene_stack.pop()
                self._eq.set_root(self._build_dispatch_root())
                raise

    def pop_scene(self) -> Scene | None:
        """Pop the topmost runtime scene; resume the one beneath.

        Returns the stopped scene, or None if the stack becomes empty
        (in which case a Quit event is signalled and the engine will
        stop on the next tick).
        """
        if self._state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            raise RuntimeError("pop_scene requires PLAY or PAUSED state")
        if not self._scene_stack:
            return None

        if self._eq:
            from expra_engine.runtime.events import (
                Quit,
                SceneContinued,
                SceneStopped,
            )

            self._eq.flush()
            self._eq.signal(SceneStopped())
            self._eq.drain()

        stopped = self._scene_stack.pop()

        if not self._scene_stack:
            # No more scenes; auto-quit
            if self._eq:
                self._eq.signal(Quit())
        else:
            if self._eq:
                self._eq.set_root(self._build_dispatch_root())
                self._eq.signal(SceneContinued())
                self._eq.drain()

        return stopped

    def replace_scene(self, scene: Scene) -> None:
        """Replace the topmost scene with a new one.

        Flushes, signals SceneStopped (to old), then SceneStarted (to new).
        """
        if self._state not in (EngineRunState.PLAY, EngineRunState.PAUSED):
            raise RuntimeError("replace_scene requires PLAY or PAUSED state")

        if self._eq:
            from expra_engine.runtime.events import SceneStarted, SceneStopped

            self._eq.flush()
            self._eq.signal(SceneStopped())
            self._eq.drain()

        if self._scene_stack:
            self._scene_stack.pop()
        self._scene_stack.append(scene)

        if self._eq:
            self._eq.set_root(self._build_dispatch_root())
            self._eq.signal(SceneStarted())
            self._eq.drain()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_runtime(self) -> None:
        """Initialise event queue, clock, scene stack, and systems."""
        from expra_engine.runtime.clock import RuntimeClock
        from expra_engine.runtime.event_queue import EventQueue
        from expra_engine.runtime.events import SceneStarted

        if self._runtime_scene:
            self._scene_stack = [self._runtime_scene]
        else:
            self._scene_stack = []

        self._transform_interpolator.clear()
        self._clock = RuntimeClock()
        self._eq = EventQueue(self._build_dispatch_root())

        for system in self._systems:
            system.start(self)

        self._start_behaviours()

        if self._scene_stack:
            self._eq.signal(SceneStarted())
            self._eq.drain()

    def _stop_runtime(self) -> None:
        """Flush events, signal SceneStopped, stop systems, teardown."""
        from expra_engine.runtime.events import SceneStopped

        if self._eq and self._scene_stack:
            self._eq.flush()
            self._eq.signal(SceneStopped())
            self._eq.drain()

        self._stop_behaviours()

        for system in reversed(self._systems):
            system.stop()

        if self._clock:
            self._clock.reset()
        self._transform_interpolator.clear()
        self._eq = None
        self._clock = None

    def _capture_behaviour_factories(
        self,
    ) -> dict[str, list[tuple[Behaviour, BehaviourFactory]]]:
        """Capture and validate edit-scene factories before scene cloning."""
        captured: dict[str, list[tuple[Behaviour, BehaviourFactory]]] = {}
        if self._edit_scene is None:
            return captured

        for entity in self._edit_scene.entities:
            behaviours = entity.behaviours
            factories = entity._behaviour_factories
            if len(behaviours) != len(factories):
                raise ValueError(
                    f"entity {entity.entity_id!r} has a missing runtime behaviour factory"
                )
            pairs: list[tuple[Behaviour, BehaviourFactory]] = []
            for behaviour, factory in zip(behaviours, factories, strict=True):
                if not callable(factory):
                    raise ValueError(
                        f"runtime behaviour factory for entity {entity.entity_id!r} "
                        "must be callable"
                    )
                pairs.append((behaviour, factory))
            if pairs:
                captured[entity.entity_id] = pairs
        return captured

    @staticmethod
    def _attach_runtime_behaviours(
        runtime_scene: Scene | None,
        captured: dict[str, list[tuple[Behaviour, BehaviourFactory]]],
    ) -> None:
        """Create and attach fresh behaviours to their cloned entities."""
        if runtime_scene is None:
            return

        for entity_id, pairs in captured.items():
            entity = runtime_scene.find_entity(entity_id)
            if entity is None:
                raise ValueError(f"runtime scene is missing entity {entity_id!r} for behaviours")
            for _, factory in pairs:
                try:
                    behaviour = factory()
                except Exception as exc:
                    raise ValueError(
                        f"runtime behaviour factory for entity {entity_id!r} failed"
                    ) from exc
                if not isinstance(behaviour, Behaviour):
                    raise ValueError(
                        f"runtime behaviour factory for entity {entity_id!r} "
                        "must return a Behaviour"
                    )
                if behaviour.entity is not None:
                    raise ValueError(
                        f"runtime behaviour factory for entity {entity_id!r} "
                        "returned an already-owned Behaviour"
                    )
                entity.add_behaviour(behaviour, runtime_factory=factory)

    def _start_behaviours(self) -> None:
        """Start behaviours attached to the base runtime scene in order."""
        if self._runtime_scene is None:
            return
        for entity in self._runtime_scene.entities:
            for behaviour in entity.behaviours:
                behaviour._set_started(True)
                behaviour.on_start()

    def _stop_behaviours(self) -> None:
        """Stop and detach behaviours before runtime teardown."""
        if self._runtime_scene is None:
            return
        for entity in self._runtime_scene.entities:
            behaviours = tuple(entity.behaviours)
            for behaviour in behaviours:
                try:
                    behaviour.on_stop()
                finally:
                    if not behaviour._destroyed:
                        behaviour.on_destroy()
                        behaviour._destroyed = True
                behaviour._set_started(False)
            for behaviour in behaviours:
                entity.remove_behaviour(behaviour)

    def _build_dispatch_root(self) -> object:
        """Build the object whose ``children`` tree receives broadcast events.

        The dispatch root aggregates: the clock, all registered systems,
        and the active scene's entity list.

        Returns a lightweight container; not a Scene.
        """
        return _DispatchRoot(
            engine=self,
            clock=self._clock,
            systems=list(self._systems),
            scene=self._scene_stack[-1] if self._scene_stack else None,
            interpolator=self._transform_interpolator,
        )

    @staticmethod
    def _materialize_scene(candidate: object, kwargs: dict) -> Scene:
        scene = candidate(**kwargs) if callable(candidate) else candidate
        if not isinstance(scene, Scene):
            raise TypeError("scene request must resolve to a Scene instance")
        return scene

    @staticmethod
    def _copy_scene(scene: Scene | None) -> Scene | None:
        """Deep-copy a scene through JSON round-trip for runtime isolation."""
        if scene is None:
            return None
        return Scene.from_dict(json.loads(json.dumps(scene.to_dict())))

    def __repr__(self) -> str:
        return (
            f"Engine(state={self._state.value!r}, "
            f"scene={repr(self._edit_scene.name) if self._edit_scene else None})"
        )


class _DispatchRoot:
    """Lightweight container that acts as the broadcast traversal root.

    ``walk()`` from event_queue.py iterates the children attribute, which
    yields the clock, systems, and scene entities.
    """

    def __init__(
        self,
        engine: Engine,
        clock: RuntimeClock | None,
        systems: list[RuntimeSystem],
        scene: Scene | None,
        interpolator: TransformInterpolator,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._systems = systems
        self._scene = scene
        self._interpolator = interpolator

    def on_scene_started(self, event: object, signal: object) -> None:
        self._interpolator.capture_scene(self._scene)

    def on_scene_stopped(self, event: object, signal: object) -> None:
        self._interpolator.clear()

    def on_scene_continued(self, event: object, signal: object) -> None:
        self._interpolator.capture_scene(self._scene)

    def on_update_complete(self, event: object) -> None:
        self._interpolator.capture_scene(self._scene)

    @property
    def children(self) -> list[object]:
        items: list[object] = []
        items.append(self._engine)
        if self._clock is not None:
            items.append(self._clock)
        items.extend(self._systems)
        if self._scene is not None:
            items.extend(self._scene.entities)
        return items
