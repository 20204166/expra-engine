"""Expra runtime event dataclasses.

Semantically adapted from ppb/events.py (PursuedPyBear, Artistic License 2.0).
All PPB-specific fields (scene, SDL objects, ppb_vector) have been removed.
Events here represent the Expra game-runtime contract, not PPB's contract.

Handler naming convention (via camel_to_snake):
    Update      → on_update
    Idle        → on_idle
    Quit        → on_quit
    SceneStarted → on_scene_started
    SceneStopped → on_scene_stopped
    ScenePaused  → on_scene_paused
    SceneContinued → on_scene_continued
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Update:
    """A simulation tick.

    Respond via ``on_update`` to advance simulation of game objects.
    ``time_delta`` is the fixed time step in seconds.
    """

    time_delta: float


@dataclass
class FrameUpdate:
    """A variable-duration frame update emitted by :meth:`Engine.tick`."""

    time_delta: float


@dataclass
class Idle:
    """One full iteration of the runtime main loop.

    Dispatched every call to Engine.tick(). Systems use this to drive
    their own timing (e.g. fixed-step accumulation). ``time_delta`` is
    the wall-clock seconds since the previous tick.
    """

    time_delta: float


@dataclass
class Quit:
    """Request the runtime to stop.

    Signal this event to request teardown on the next ``Engine.tick()``.
    Respond via ``on_quit`` to perform teardown work before the runtime leaves
    PLAY state.
    """


@dataclass
class SceneStarted:
    """A scene has started running.

    Dispatched after a scene is pushed onto the runtime scene stack.
    Respond via ``on_scene_started`` for per-scene initialisation.
    """


@dataclass
class SceneStopped:
    """A scene has stopped and will be discarded.

    Dispatched before the scene is popped from the runtime scene stack.
    Respond via ``on_scene_stopped`` for per-scene teardown/saving.
    """


@dataclass
class ScenePaused:
    """The active scene is being paused while a new scene runs on top."""


@dataclass
class SceneContinued:
    """A previously paused scene is resuming."""


@dataclass
class ReplaceScene:
    """Request the current scene be replaced with a new one.

    ``new_scene`` must be a callable that returns a scene instance, or
    a scene instance directly. ``kwargs`` are forwarded to a callable.
    """

    new_scene: object
    kwargs: dict = field(default_factory=dict)


@dataclass
class StartScene:
    """Request a new scene to be pushed on top of the current one.

    The current scene pauses; when the new scene stops, the paused
    scene continues.
    """

    new_scene: object
    kwargs: dict = field(default_factory=dict)


@dataclass
class StopScene:
    """Request the current scene to stop.

    If a paused scene is beneath it on the stack, that scene continues.
    If the stack becomes empty, a Quit event is signalled automatically.
    """
