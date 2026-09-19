"""Engine — runtime and editor state owner.

ENGINE OWNS GAME STATE.

The Engine holds:
- EngineRunState (EDIT / PLAY / PAUSED)
- the active Project
- the active Scene

The editor presents and edits that state through the coordinator boundary.
The engine never owns widgets or Tk resources.
"""

from __future__ import annotations

import json
import time
from enum import Enum

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene


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
    the caller via ``update(dt)``.
    """

    def __init__(self) -> None:
        self._state = EngineRunState.EDIT
        self._project: Project | None = None
        self._edit_scene: Scene | None = None
        self._runtime_scene: Scene | None = None
        self._last_update: float | None = None

    @property
    def run_state(self) -> EngineRunState:
        return self._state

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def active_scene(self) -> Scene | None:
        """The scene currently visible in the editor or running at runtime."""
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            return self._runtime_scene
        return self._edit_scene

    @property
    def edit_scene(self) -> Scene | None:
        return self._edit_scene

    def set_project(self, project: Project | None) -> None:
        self._project = project

    def set_scene(self, scene: Scene | None) -> None:
        """Set the scene for editing. Resets any running play state first."""
        if self._state != EngineRunState.EDIT:
            self.stop()
        self._edit_scene = scene
        if self._project is not None and scene is not None:
            self._project.set_active_scene(scene)

    def play(self) -> bool:
        """Enter PLAY state. Returns True if state changed."""
        if self._state == EngineRunState.EDIT:
            self._runtime_scene = self._copy_scene(self._edit_scene)
            self._state = EngineRunState.PLAY
            self._last_update = time.monotonic()
            return True
        if self._state == EngineRunState.PAUSED:
            self._state = EngineRunState.PLAY
            self._last_update = time.monotonic()
            return True
        return False

    def pause(self) -> bool:
        """Enter PAUSED state. Returns True if state changed."""
        if self._state == EngineRunState.PLAY:
            self._state = EngineRunState.PAUSED
            return True
        return False

    def stop(self) -> bool:
        """Return to EDIT state, restoring the original edit scene. Returns True if changed."""
        if self._state in (EngineRunState.PLAY, EngineRunState.PAUSED):
            self._runtime_scene = None
            self._state = EngineRunState.EDIT
            self._last_update = None
            return True
        return False

    def update(self, dt: float | None = None) -> float:
        """Advance the runtime by ``dt`` seconds (defaults to wall-clock elapsed).

        Only meaningful in PLAY state; safe to call at any time.
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
