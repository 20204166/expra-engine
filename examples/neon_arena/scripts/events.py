"""Gameplay events used by the scripted Neon Arena mode."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetCollected:
    """The player reached the target."""


@dataclass(frozen=True)
class GameWon:
    """The arena reached its win condition."""


@dataclass(frozen=True)
class RestartRequested:
    """The player requested a fresh round."""
