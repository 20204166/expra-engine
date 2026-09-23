"""Renderer-neutral sprite metadata and deterministic animation state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

__all__ = (
    "AnimationClip",
    "AnimationFrame",
    "Animator",
    "SpriteMetadata",
    "SpriteRegion",
    "SpriteSheet",
)


@dataclass(frozen=True)
class SpriteMetadata:
    """Identity and scaling policy for a sprite, without loading its asset."""

    texture: object
    pixels_per_unit: float = 100.0
    preserve_aspect: bool = True

    def __post_init__(self) -> None:
        if not isfinite(self.pixels_per_unit) or self.pixels_per_unit <= 0.0:
            raise ValueError("pixels_per_unit must be finite and positive")


@dataclass(frozen=True)
class SpriteRegion:
    """A pixel rectangle exposed to a renderer adapter."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.x, self.y, self.width, self.height)):
            raise ValueError("sprite regions require integer pixel values")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("sprite regions require non-negative origins and positive size")

    def __str__(self) -> str:
        return f"{self.x}, {self.y}, {self.width}, {self.height}"


@dataclass(frozen=True)
class SpriteSheet:
    """A regular sheet whose tiles can be addressed without touching an asset."""

    texture: object
    tile_width: int
    tile_height: int
    columns: int
    rows: int

    def __post_init__(self) -> None:
        if self.tile_width <= 0 or self.tile_height <= 0 or self.columns <= 0 or self.rows <= 0:
            raise ValueError("sprite-sheet dimensions must be positive")

    def region(self, column: int, row: int) -> SpriteRegion:
        if not 0 <= column < self.columns or not 0 <= row < self.rows:
            raise ValueError("sprite-sheet tile coordinates are out of bounds")
        return SpriteRegion(
            column * self.tile_width,
            row * self.tile_height,
            self.tile_width,
            self.tile_height,
        )


@dataclass(frozen=True)
class AnimationFrame:
    region: SpriteRegion
    duration: float

    def __post_init__(self) -> None:
        if not isfinite(self.duration) or self.duration <= 0.0:
            raise ValueError("frame duration must be finite and positive")


@dataclass(frozen=True)
class AnimationClip:
    frames: Sequence[AnimationFrame]
    loop: bool = False

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        if not frames:
            raise ValueError("animation clips require at least one frame")
        object.__setattr__(self, "frames", frames)


class Animator:
    """Advance named immutable clips from deltas supplied by the runtime loop."""

    def __init__(
        self,
        clips: Mapping[str, AnimationClip],
        *,
        states: Mapping[str, str] | None = None,
    ) -> None:
        self._clips = dict(clips)
        self._states = dict(states or {})
        self._clip: AnimationClip | None = None
        self._state: str | None = None
        self._frame_index = 0
        self._frame_elapsed = 0.0
        self._playing = False

    @property
    def current_clip(self) -> AnimationClip | None:
        return self._clip

    @property
    def current_frame(self) -> AnimationFrame | None:
        if self._clip is None:
            return None
        return self._clip.frames[self._frame_index]

    @property
    def state(self) -> str | None:
        return self._state

    @property
    def playing(self) -> bool:
        return self._playing

    def play(self, clip_name: str) -> None:
        clip = self._clips[clip_name]
        self._clip = clip
        self._state = None
        self._frame_index = 0
        self._frame_elapsed = 0.0
        self._playing = True

    def set_state(self, state_name: str) -> None:
        clip_name = self._states[state_name]
        clip = self._clips[clip_name]
        self._clip = clip
        self._state = state_name
        self._frame_index = 0
        self._frame_elapsed = 0.0
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def resume(self) -> None:
        if self._clip is not None:
            self._playing = True

    def update(self, delta: float) -> None:
        if not isfinite(delta) or delta < 0.0:
            raise ValueError("animation delta must be finite and non-negative")
        if not self._playing or self._clip is None:
            return

        remaining = delta
        while remaining > 0.0 and self._playing:
            frame = self._clip.frames[self._frame_index]
            until_next = frame.duration - self._frame_elapsed
            if remaining < until_next:
                self._frame_elapsed += remaining
                return
            remaining -= until_next
            self._frame_elapsed = 0.0
            if self._frame_index + 1 < len(self._clip.frames):
                self._frame_index += 1
            elif self._clip.loop:
                self._frame_index = 0
            else:
                self._frame_elapsed = frame.duration
                self._playing = False
