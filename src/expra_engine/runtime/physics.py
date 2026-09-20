"""Backend-neutral physics query result contracts.

Inspired by Ursina's hit_info.py, raycast.py concepts.  No Panda3D
collision traverser; these are pure data contracts for future physics
backends to populate.

Trigger lifecycle semantics are also defined here as an event vocabulary
so gameplay code can use consistent enter/stay/exit events regardless of
the backend physics engine chosen later.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

__all__ = (
    "HitResult2D",
    "TriggerEvent",
    "TriggerPhase",
)

TriggerPhase = str  # "entered" | "stayed" | "exited"


@dataclass(frozen=True)
class HitResult2D:
    """The result of a 2D collision query.

    ``hit`` is False for a no-hit result; all other fields are then at
    their default "empty" values.  When ``hit`` is True, ``entity_id``
    identifies the entity that was struck.

    Fields are backend-neutral; a physics adapter populates them.
    ``fraction`` is in [0, 1] when the query is a sweep/raycast (0 = start,
    1 = end of the cast segment).
    """

    hit: bool = False
    entity_id: str | None = None
    point: tuple[float, float] | None = None
    normal: tuple[float, float] | None = None
    distance: float | None = None
    fraction: float | None = None

    def __post_init__(self) -> None:
        if self.hit and self.entity_id is None:
            raise ValueError("entity_id must be provided when hit is True")
        if self.distance is not None:
            d = float(self.distance)
            if not isfinite(d) or d < 0.0:
                raise ValueError("distance must be finite and non-negative")
            object.__setattr__(self, "distance", d)
        if self.fraction is not None:
            f = float(self.fraction)
            if not isfinite(f) or not 0.0 <= f <= 1.0:
                raise ValueError("fraction must be in [0, 1]")
            object.__setattr__(self, "fraction", f)

    @classmethod
    def no_hit(cls) -> HitResult2D:
        """Return a canonical empty (no-hit) result."""
        return cls(hit=False)

    @staticmethod
    def nearest(results: list[HitResult2D]) -> HitResult2D | None:
        """Return the hit result closest to the cast origin, or None.

        Hits without a distance are placed after those with one.
        """
        hits = [r for r in results if r.hit]
        if not hits:
            return None
        return min(
            hits,
            key=lambda r: r.distance if r.distance is not None else float("inf"),
        )


@dataclass(frozen=True)
class TriggerEvent:
    """A lifecycle event emitted when an entity enters, stays in, or exits a trigger area.

    ``phase`` is one of: ``"entered"``, ``"stayed"``, ``"exited"``.

    Backends must guarantee:
      - ``"entered"`` fires exactly once per overlapping pair.
      - ``"exited"`` fires exactly once after ``"entered"``.
      - No ``"exited"`` without a prior ``"entered"`` for the same pair.
    """

    phase: TriggerPhase
    trigger_id: str
    body_id: str

    def __post_init__(self) -> None:
        if self.phase not in {"entered", "stayed", "exited"}:
            raise ValueError(
                f"TriggerEvent phase must be 'entered', 'stayed', or 'exited', got {self.phase!r}"
            )
        if not self.trigger_id or not self.body_id:
            raise ValueError("trigger_id and body_id must not be empty")
