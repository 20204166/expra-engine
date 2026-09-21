"""Renderer-neutral AnimatedSprite2D state and serializable frame data.

Adapted from Godot AnimatedSprite2D while preserving Expra ownership:
- no Node2D, RenderingServer, accessibility server, editor notifications, or loop
- no texture objects or backend draw calls
- immutable frame/animation data
- serializable component configuration
- caller-driven playback state with deterministic events
- reverse, linear-loop, ping-pong, autoplay, frame progress, offset and flips

The existing Expra renderer remains responsible for turning ``SpriteFrameView``
into a texture draw. Runtime scheduling remains owned by Expra's existing
FrameUpdate/RuntimeSystem path.

Godot Engine source is MIT licensed:
Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md).
Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, cast

from expra_engine.core.component import Component
from expra_engine.runtime.animation import SpriteRegion

__all__ = (
    "AnimatedSprite2DComponent",
    "AnimatedSpritePlayer2D",
    "SpriteAnimation2D",
    "SpriteEvent2D",
    "SpriteFrame2D",
    "SpriteFrameView",
    "SpriteFrames2D",
    "SpriteLoopMode",
)


class SpriteLoopMode(StrEnum):
    NONE = "none"
    LINEAR = "linear"
    PINGPONG = "pingpong"


_EVENT_KINDS = frozenset(
    {
        "sprite_frames_changed",
        "animation_changed",
        "frame_changed",
        "animation_looped",
        "animation_finished",
    }
)


def _finite(value: object, name: str) -> float:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _progress(value: object) -> float:
    result = _finite(value, "frame_progress")
    if not 0.0 <= result <= 1.0:
        raise ValueError("frame_progress must be in [0, 1]")
    return result


def _vec2(value: object, name: str) -> tuple[float, float]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain two finite numbers")
    try:
        items: tuple[Any, ...] = tuple(cast(Any, value))
    except TypeError as exc:
        raise ValueError(f"{name} must contain two finite numbers") from exc
    if len(items) != 2:
        raise ValueError(f"{name} must contain two finite numbers")
    return (_finite(items[0], f"{name}.x"), _finite(items[1], f"{name}.y"))


def _region_dict(region: SpriteRegion | None) -> list[int] | None:
    if region is None:
        return None
    return [region.x, region.y, region.width, region.height]


def _region(value: object) -> SpriteRegion | None:
    if value is None or isinstance(value, SpriteRegion):
        return value
    if isinstance(value, (str, bytes)):
        raise ValueError("region must contain x, y, width, height")
    try:
        items: tuple[Any, ...] = tuple(cast(Any, value))
    except TypeError as exc:
        raise ValueError("region must contain x, y, width, height") from exc
    if len(items) != 4:
        raise ValueError("region must contain x, y, width, height")
    return SpriteRegion(*(int(item) for item in items))


@dataclass(frozen=True)
class SpriteFrame2D:
    """One frame: logical texture asset, optional atlas region and duration weight."""

    asset_id: str
    duration: float = 1.0
    region: SpriteRegion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, str) or not self.asset_id:
            raise ValueError("asset_id must not be empty")
        object.__setattr__(self, "duration", _positive(self.duration, "duration"))
        object.__setattr__(self, "region", _region(self.region))

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "duration": self.duration,
            "region": _region_dict(self.region),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SpriteFrame2D:
        return cls(
            str(data["asset_id"]),
            duration=data.get("duration", 1.0),
            region=_region(data.get("region")),
        )


@dataclass(frozen=True)
class SpriteAnimation2D:
    """Immutable named-animation payload.

    ``speed_fps`` is the base frames-per-second rate. Each frame's ``duration``
    is a positive relative multiplier, matching Godot SpriteFrames' ability to
    make individual frames last longer or shorter than the base frame period.
    """

    frames: Sequence[SpriteFrame2D]
    speed_fps: float = 5.0
    loop_mode: SpriteLoopMode = SpriteLoopMode.LINEAR

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        if not frames:
            raise ValueError("sprite animations require at least one frame")
        if not all(isinstance(frame, SpriteFrame2D) for frame in frames):
            raise TypeError("frames must contain SpriteFrame2D values")
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "speed_fps", _positive(self.speed_fps, "speed_fps"))
        if not isinstance(self.loop_mode, SpriteLoopMode):
            object.__setattr__(self, "loop_mode", SpriteLoopMode(str(self.loop_mode)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_fps": self.speed_fps,
            "loop_mode": self.loop_mode.value,
            "frames": [frame.to_dict() for frame in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SpriteAnimation2D:
        raw_frames = data.get("frames", ())
        if not isinstance(raw_frames, Sequence) or isinstance(raw_frames, (str, bytes)):
            raise ValueError("animation frames must be a sequence")
        return cls(
            tuple(SpriteFrame2D.from_dict(frame) for frame in raw_frames),
            speed_fps=data.get("speed_fps", 5.0),
            loop_mode=SpriteLoopMode(str(data.get("loop_mode", "linear"))),
        )


class SpriteFrames2D:
    """Immutable mapping of animation names to frame sequences."""

    def __init__(self, animations: Mapping[str, SpriteAnimation2D] | None = None) -> None:
        copied: dict[str, SpriteAnimation2D] = {}
        for name, animation in (animations or {}).items():
            key = str(name)
            if not key:
                raise ValueError("animation names must not be empty")
            if not isinstance(animation, SpriteAnimation2D):
                raise TypeError("animations must contain SpriteAnimation2D values")
            copied[key] = animation
        self._animations = MappingProxyType(copied)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._animations)

    def __len__(self) -> int:
        return len(self._animations)

    def __contains__(self, name: object) -> bool:
        return name in self._animations

    def get(self, name: str) -> SpriteAnimation2D:
        try:
            return self._animations[name]
        except KeyError as exc:
            raise KeyError(f"unknown sprite animation: {name!r}") from exc

    def first_name(self) -> str | None:
        return next(iter(self._animations), None)

    def to_dict(self) -> dict[str, Any]:
        return {name: animation.to_dict() for name, animation in self._animations.items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SpriteFrames2D:
        return cls(
            {
                str(name): SpriteAnimation2D.from_dict(animation)
                for name, animation in data.items()
            }
        )


class AnimatedSprite2DComponent(Component):
    """Serializable AnimatedSprite2D configuration; runtime state lives elsewhere."""

    component_type = "animated_sprite"

    def __init__(
        self,
        frames: SpriteFrames2D | Mapping[str, Any] | None = None,
        *,
        animation: str = "default",
        autoplay: str = "",
        frame: int = 0,
        frame_progress: float = 0.0,
        speed_scale: float = 1.0,
        centered: bool = True,
        offset: tuple[float, float] = (0.0, 0.0),
        flip_h: bool = False,
        flip_v: bool = False,
        layer: int = 0,
        visible: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)
        if frames is None:
            self.frames = SpriteFrames2D()
        elif isinstance(frames, SpriteFrames2D):
            self.frames = frames
        else:
            self.frames = SpriteFrames2D.from_dict(frames)
        self.animation = str(animation)
        self.autoplay = str(autoplay)
        self.frame = max(0, int(frame))
        self.frame_progress = _progress(frame_progress)
        self.speed_scale = _finite(speed_scale, "speed_scale")
        self.centered = bool(centered)
        self.offset = _vec2(offset, "offset")
        self.flip_h = bool(flip_h)
        self.flip_v = bool(flip_v)
        self.layer = int(layer)
        self.visible = bool(visible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.component_type,
            "enabled": self.enabled,
            "frames": self.frames.to_dict(),
            "animation": self.animation,
            "autoplay": self.autoplay,
            "frame": self.frame,
            "frame_progress": self.frame_progress,
            "speed_scale": self.speed_scale,
            "centered": self.centered,
            "offset": list(self.offset),
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
            "layer": self.layer,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AnimatedSprite2DComponent:
        raw_frames = data.get("frames", {})
        if not isinstance(raw_frames, Mapping):
            raise ValueError("frames must be a mapping")
        return cls(
            SpriteFrames2D.from_dict(raw_frames),
            animation=str(data.get("animation", "default")),
            autoplay=str(data.get("autoplay", "")),
            frame=int(data.get("frame", 0)),
            frame_progress=data.get("frame_progress", 0.0),
            speed_scale=data.get("speed_scale", 1.0),
            centered=bool(data.get("centered", True)),
            offset=tuple(data.get("offset", (0.0, 0.0))),  # type: ignore[arg-type]
            flip_h=bool(data.get("flip_h", False)),
            flip_v=bool(data.get("flip_v", False)),
            layer=int(data.get("layer", 0)),
            visible=bool(data.get("visible", True)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class SpriteEvent2D:
    event_handler_name: ClassVar[str] = "on_sprite_event"
    kind: str
    animation: str
    frame: int
    count: int = 1

    def __post_init__(self) -> None:
        if self.kind not in _EVENT_KINDS:
            raise ValueError(f"unsupported sprite event: {self.kind!r}")
        if self.frame < 0 or self.count <= 0:
            raise ValueError("event frame/count are invalid")


@dataclass(frozen=True)
class SpriteFrameView:
    asset_id: str
    region: SpriteRegion | None
    animation: str
    frame: int
    progress: float
    centered: bool
    offset: tuple[float, float]
    flip_h: bool
    flip_v: bool
    layer: int
    visible: bool


class AnimatedSpritePlayer2D:
    """Caller-driven runtime state for an :class:`AnimatedSprite2DComponent`."""

    def __init__(self, component: AnimatedSprite2DComponent) -> None:
        if not isinstance(component, AnimatedSprite2DComponent):
            raise TypeError("component must be AnimatedSprite2DComponent")
        self.component = component
        self.frames = component.frames
        self.animation = component.animation
        if self.animation not in self.frames and self.frames.first_name() is not None:
            self.animation = self.frames.first_name() or ""
        self.frame = component.frame
        self.frame_progress = component.frame_progress
        self.speed_scale = component.speed_scale
        self.custom_speed_scale = 1.0
        self.playing = False
        self._clamp_frame()

    @property
    def current_animation(self) -> SpriteAnimation2D | None:
        if self.animation not in self.frames:
            return None
        return self.frames.get(self.animation)

    @property
    def current_frame(self) -> SpriteFrame2D | None:
        animation = self.current_animation
        if animation is None:
            return None
        return animation.frames[self.frame]

    @property
    def playing_speed(self) -> float:
        return self.speed_scale * self.custom_speed_scale if self.playing else 0.0

    @property
    def view(self) -> SpriteFrameView | None:
        frame = self.current_frame
        if frame is None:
            return None
        return SpriteFrameView(
            frame.asset_id,
            frame.region,
            self.animation,
            self.frame,
            self.frame_progress,
            self.component.centered,
            self.component.offset,
            self.component.flip_h,
            self.component.flip_v,
            self.component.layer,
            self.component.visible and self.component.enabled,
        )

    def start(self) -> tuple[SpriteEvent2D, ...]:
        if self.component.autoplay and self.component.autoplay in self.frames:
            return self.play(self.component.autoplay)
        return ()

    def set_frames(self, frames: SpriteFrames2D) -> tuple[SpriteEvent2D, ...]:
        if not isinstance(frames, SpriteFrames2D):
            raise TypeError("frames must be SpriteFrames2D")
        self.frames = frames
        events = [SpriteEvent2D("sprite_frames_changed", self.animation, self.frame)]
        if self.animation not in frames:
            replacement = frames.first_name() or ""
            if replacement != self.animation:
                self.animation = replacement
                events.append(SpriteEvent2D("animation_changed", self.animation, 0))
        self.stop()
        return tuple(events)

    def set_animation(self, name: str) -> tuple[SpriteEvent2D, ...]:
        name = str(name)
        if name not in self.frames:
            raise ValueError(f"unknown sprite animation: {name!r}")
        if name == self.animation:
            return ()
        self.animation = name
        animation = self.frames.get(name)
        if self.playing_speed < 0.0:
            self.frame = len(animation.frames) - 1
            self.frame_progress = 1.0
        else:
            self.frame = 0
            self.frame_progress = 0.0
        return (SpriteEvent2D("animation_changed", self.animation, self.frame),)

    def play(
        self,
        name: str | None = None,
        custom_speed: float = 1.0,
        from_end: bool = False,
    ) -> tuple[SpriteEvent2D, ...]:
        custom_speed = _finite(custom_speed, "custom_speed")
        target = self.animation if name in (None, "") else str(name)
        if target not in self.frames:
            raise ValueError(f"unknown sprite animation: {target!r}")
        animation = self.frames.get(target)
        events: list[SpriteEvent2D] = []
        changed = target != self.animation
        self.custom_speed_scale = custom_speed
        self.playing = True
        if changed:
            self.animation = target
            if from_end:
                self.frame = len(animation.frames) - 1
                self.frame_progress = 1.0
            else:
                self.frame = 0
                self.frame_progress = 0.0
            events.append(SpriteEvent2D("animation_changed", self.animation, self.frame))
        else:
            backward = self.speed_scale * self.custom_speed_scale < 0.0
            last = len(animation.frames) - 1
            if from_end and backward and self.frame == 0 and self.frame_progress <= 0.0:
                self.frame, self.frame_progress = last, 1.0
            elif not from_end and not backward and self.frame == last and self.frame_progress >= 1.0:
                self.frame, self.frame_progress = 0, 0.0
        return tuple(events)

    def play_backwards(self, name: str | None = None) -> tuple[SpriteEvent2D, ...]:
        return self.play(name, custom_speed=-1.0, from_end=True)

    def pause(self) -> None:
        self.playing = False

    def stop(self) -> None:
        self.playing = False
        self.custom_speed_scale = 1.0
        self.frame = 0
        self.frame_progress = 0.0
        self._clamp_frame()

    def set_frame(self, frame: int) -> tuple[SpriteEvent2D, ...]:
        old = self.frame
        self.frame = int(frame)
        self._clamp_frame()
        self.frame_progress = 1.0 if self.playing_speed < 0.0 else 0.0
        if self.frame == old:
            return ()
        return (SpriteEvent2D("frame_changed", self.animation, self.frame),)

    def set_frame_progress(self, progress: float) -> None:
        self.frame_progress = _progress(progress)

    def set_frame_and_progress(
        self, frame: int, progress: float
    ) -> tuple[SpriteEvent2D, ...]:
        old = self.frame
        self.frame = int(frame)
        self._clamp_frame()
        self.frame_progress = _progress(progress)
        if self.frame == old:
            return ()
        return (SpriteEvent2D("frame_changed", self.animation, self.frame),)

    def advance(self, delta: float) -> tuple[SpriteEvent2D, ...]:
        remaining = _finite(delta, "delta")
        if remaining < 0.0:
            raise ValueError("delta must be non-negative")
        animation = self.current_animation
        if not self.playing or animation is None or remaining == 0.0:
            return ()
        rate = animation.speed_fps * abs(self.speed_scale * self.custom_speed_scale)
        if rate == 0.0:
            return ()

        events: list[SpriteEvent2D] = []
        transitions = 0
        while remaining > 0.0 and self.playing:
            animation = self.current_animation
            assert animation is not None
            frame = animation.frames[self.frame]
            frame_seconds = frame.duration / rate
            forward = self.speed_scale * self.custom_speed_scale >= 0.0
            fraction_left = (1.0 - self.frame_progress) if forward else self.frame_progress
            time_left = max(0.0, fraction_left * frame_seconds)

            if (
                time_left > 0.0
                and remaining < time_left
                and not math.isclose(remaining, time_left, rel_tol=1e-12, abs_tol=1e-12)
            ):
                change = remaining / frame_seconds
                self.frame_progress += change if forward else -change
                remaining = 0.0
                break

            remaining = max(0.0, remaining - time_left)
            self.frame_progress = 1.0 if forward else 0.0
            emitted = self._cross_boundary(forward)
            events.extend(emitted)
            transitions += 1

            # Positive finite frame durations guarantee progress, but this guard
            # protects integrations that mutate animation data between events.
            if transitions > 1_000_000:
                raise RuntimeError("animated sprite exceeded safe transition limit")

        return tuple(events)

    def _cross_boundary(self, forward: bool) -> tuple[SpriteEvent2D, ...]:
        animation = self.current_animation
        assert animation is not None
        last = len(animation.frames) - 1
        events: list[SpriteEvent2D] = []

        if forward and self.frame < last:
            self.frame += 1
            self.frame_progress = 0.0
            return (SpriteEvent2D("frame_changed", self.animation, self.frame),)
        if not forward and self.frame > 0:
            self.frame -= 1
            self.frame_progress = 1.0
            return (SpriteEvent2D("frame_changed", self.animation, self.frame),)

        if animation.loop_mode is SpriteLoopMode.NONE:
            self.frame = last if forward else 0
            self.frame_progress = 1.0 if forward else 0.0
            self.playing = False
            return (SpriteEvent2D("animation_finished", self.animation, self.frame),)

        events.append(SpriteEvent2D("animation_looped", self.animation, self.frame))
        if animation.loop_mode is SpriteLoopMode.PINGPONG:
            self.custom_speed_scale *= -1.0
            self.frame_progress = 1.0 if forward else 0.0
            return tuple(events)

        self.frame = 0 if forward else last
        self.frame_progress = 0.0 if forward else 1.0
        events.append(SpriteEvent2D("frame_changed", self.animation, self.frame))
        return tuple(events)

    def _clamp_frame(self) -> None:
        animation = self.current_animation
        if animation is None:
            self.frame = 0
            self.frame_progress = 0.0
            return
        self.frame = max(0, min(self.frame, len(animation.frames) - 1))
