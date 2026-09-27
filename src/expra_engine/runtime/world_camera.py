"""Canonical World camera-context ownership without owning camera motion state."""

from __future__ import annotations

import math

from expra_engine.runtime.world_policy import WorldCameraContext

__all__ = ("WorldCameraContextMixin",)


class WorldCameraContextMixin:
    """Compute the continuous World gameplay-camera context for one active World.

    Split from ``world_streaming.py``: camera context is an explainable output
    of residency, not residency itself. The hosting system owns the bound
    source data; this mixin derives the inspectable ``WorldCameraContext``.
    """

    def primary_level(self) -> str | None:
        """Return the Level containing the explicitly configured primary anchor."""
        if self.world.primary_anchor_id is not None:
            return self.current_level(self.world.primary_anchor_id)
        return self.world.initial_level_id

    @property
    def primary_anchor_entity_id(self) -> str | None:
        if self.world.primary_anchor_id is None:
            return None
        anchor = next(
            (item for item in self.streaming_anchors() if item.anchor_id == self.world.primary_anchor_id),
            None,
        )
        return anchor.entity_id if anchor is not None else None

    @property
    def camera_context(self) -> WorldCameraContext:
        primary = self.primary_level()
        context_level = self._camera_context_level_id or primary
        effective_levels = set(self.active_levels())
        if context_level is not None:
            effective_levels.add(context_level)
        bounds = [
            self._level_camera_bounds[level_id]
            for level_id in effective_levels
            if level_id in self._level_camera_bounds
            and self._level_camera_bounds[level_id] is not None
        ]
        if bounds:
            effective_bounds = (
                min(value[0] for value in bounds),
                min(value[1] for value in bounds),
                max(value[2] for value in bounds),
                max(value[3] for value in bounds),
            )
        else:
            effective_bounds = None
        return WorldCameraContext(
            camera_id=f"world-camera:{self.world.world_id}",
            primary_level_id=primary,
            camera_context_level_id=context_level,
            follow_target_entity_id=self.primary_anchor_entity_id,
            active_level_ids=self.active_levels(),
            effective_bounds=effective_bounds,
            bounds_sources=tuple(
                sorted(
                    level_id
                    for level_id in effective_levels
                    if self._level_camera_bounds.get(level_id) is not None
                )
            ),
            recenter_generation=self._camera_recenter_generation,
        )

    def report_camera_view(
        self,
        position: tuple[float, float],
        size: tuple[float, float],
    ) -> None:
        """Advance Level camera context only after the view fits in the primary Level."""
        self._assert_owner()
        values = (*position, *size)
        if len(position) != 2 or len(size) != 2 or not all(
            math.isfinite(float(value)) for value in values
        ) or size[0] <= 0.0 or size[1] <= 0.0:
            raise ValueError("camera view requires finite World position and positive size")
        self._camera_position = (float(position[0]), float(position[1]))
        self._camera_view_size = (float(size[0]), float(size[1]))
        primary = self.primary_level()
        if primary is None or primary == self._camera_context_level_id:
            return
        bounds = self._level_camera_bounds.get(primary)
        if bounds is None:
            self._camera_context_level_id = primary
            return
        half_width, half_height = self._camera_view_size[0] / 2, self._camera_view_size[1] / 2
        if (
            self._camera_position[0] - half_width >= bounds[0]
            and self._camera_position[0] + half_width <= bounds[2]
            and self._camera_position[1] - half_height >= bounds[1]
            and self._camera_position[1] + half_height <= bounds[3]
        ):
            self._camera_context_level_id = primary
