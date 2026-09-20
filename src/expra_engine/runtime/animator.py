"""Pure-data animation state machine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnimatorStateMachine:
    states: dict[str, str]
    initial_state: str
    _current: str = field(init=False, repr=False)
    _previous: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.initial_state not in self.states:
            raise ValueError(f"initial_state {self.initial_state!r} not in states")
        self._current = self.initial_state

    @property
    def current_state(self) -> str:
        return self._current

    @property
    def current_clip_id(self) -> str:
        return self.states[self._current]

    @property
    def previous_state(self) -> str | None:
        return self._previous

    def set_state(self, state: str) -> bool:
        if state not in self.states:
            raise ValueError(f"Unknown state {state!r}")
        if state == self._current:
            return False
        self._previous = self._current
        self._current = state
        return True


__all__ = ["AnimatorStateMachine"]
