"""Audio system contracts — data types only, no playback backend.

This module defines the renderer-neutral audio data model.  No actual audio
playback is implemented here; a backend adapter (e.g. pygame.mixer,
sounddevice) will implement the contracts using these types.

Inspired by Ursina's audio.py and music_system.py bus concepts.  Panda3D
audio infrastructure is deliberately absent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = (
    "AudioBus",
    "AudioClip",
    "AudioMixer",
)

_BUS_NAMES = frozenset({"master", "music", "sfx", "ambience", "dialogue", "ui"})


def _volume(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return max(0.0, min(1.0, v))


@dataclass
class AudioBus:
    """One named mixing bus with independent volume and mute state.

    ``name`` must be a known bus name so callers can depend on a stable set.
    Volume is clamped to [0, 1]; muting a bus silences it without changing
    the stored volume.
    """

    name: str
    volume: float = 1.0
    muted: bool = False

    def __post_init__(self) -> None:
        if self.name not in _BUS_NAMES:
            raise ValueError(f"unknown bus {self.name!r}; expected one of {sorted(_BUS_NAMES)}")
        self.volume = _volume(self.volume, "volume")

    @property
    def effective_volume(self) -> float:
        """Return the actual output volume (0.0 when muted)."""
        return 0.0 if self.muted else self.volume

    def set_volume(self, volume: float) -> None:
        self.volume = _volume(volume, "volume")


@dataclass
class AudioClip:
    """Metadata for one audio asset reference; no file bytes stored here."""

    asset_id: str
    bus: str = "sfx"
    volume: float = 1.0
    pitch: float = 1.0
    pan: float = 0.0
    loop: bool = False

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id cannot be empty")
        if self.bus not in _BUS_NAMES:
            raise ValueError(f"unknown bus {self.bus!r}; expected one of {sorted(_BUS_NAMES)}")
        self.volume = _volume(self.volume, "volume")
        if not math.isfinite(self.pitch) or self.pitch <= 0.0:
            raise ValueError("pitch must be finite and positive")
        pan = float(self.pan)
        if not math.isfinite(pan) or not -1.0 <= pan <= 1.0:
            raise ValueError("pan must be in [-1, 1]")
        self.pan = pan

    def effective_volume(self, mixer: AudioMixer) -> float:
        """Compute final output volume: master x bus x clip."""
        master = mixer.buses["master"].effective_volume
        bus_vol = mixer.buses[self.bus].effective_volume
        return master * bus_vol * self.volume


@dataclass
class AudioMixer:
    """Container for all named buses, providing effective-volume queries."""

    buses: dict[str, AudioBus] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in _BUS_NAMES:
            if name not in self.buses:
                self.buses[name] = AudioBus(name)

    def bus(self, name: str) -> AudioBus:
        if name not in self.buses:
            raise KeyError(f"bus {name!r} not found")
        return self.buses[name]
