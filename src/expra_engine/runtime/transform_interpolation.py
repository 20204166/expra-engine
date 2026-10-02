"""Deterministic fixed-tick transform interpolation.

Extracted from the useful runtime behavior of Godot's SceneTreeFTI and adapted
to Expra's existing renderer-neutral ``Transform`` contract.

This module owns interpolation snapshots only. It does not own the game loop,
scene stack, event queue, entity hierarchy, timing, rendering, or persistence.

Godot Engine source is MIT licensed:
Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md).
Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to inclusion of this notice.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""

from __future__ import annotations

import math
from collections.abc import Hashable
from dataclasses import dataclass

from expra_engine.core.component import TransformComponent
from expra_engine.core.math_utils import lerp, lerp_angle
from expra_engine.core.scene import Scene
from expra_engine.runtime.rendering import Transform

__all__ = ("TransformInterpolator",)


def _fraction(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("interpolation fraction must be finite and in [0, 1]")
    return value


def _interpolate(previous: Transform, current: Transform, alpha: float) -> Transform:
    # Expra's Transform.rotation is degrees around Z. Interpolate over the
    # shortest arc (via lerp_angle) so 350° -> 10° passes through 0°, not 180°.
    return Transform(
        position=(
            lerp(previous.position[0], current.position[0], alpha),
            lerp(previous.position[1], current.position[1], alpha),
            lerp(previous.position[2], current.position[2], alpha),
        ),
        rotation=lerp_angle(previous.rotation, current.rotation, alpha),
        scale=(
            lerp(previous.scale[0], current.scale[0], alpha),
            lerp(previous.scale[1], current.scale[1], alpha),
            lerp(previous.scale[2], current.scale[2], alpha),
        ),
    )


@dataclass
class _State:
    previous: Transform
    current: Transform
    parent: Hashable | None
    interpolated: bool
    last_tick: int
    reset_requested: bool = False


class TransformInterpolator:
    """Store fixed-tick transform snapshots and sample render transforms.

    Integration model::

        interpolator.begin_tick()
        for entity in scene.iter_entities():
            interpolator.capture(
                entity.entity_id,
                transform,
                parent=entity.parent_id,
            )
        interpolator.end_tick(prune=True)

        render_transform = interpolator.sample_world(
            entity.entity_id,
            clock.interpolation_fraction,
        )

    ``capture`` may be called more than once for the same key during one tick.
    The previous snapshot advances only on the first capture in that tick,
    matching the important SceneTreeFTI invariant that repeated writes in one
    physics tick must not destroy the previous-tick state.

    Interpolation state is runtime-only and must not be serialized.
    """

    def __init__(self) -> None:
        self._states: dict[Hashable, _State] = {}
        self._tick = 0
        self._tick_open = False
        self._seen: set[Hashable] = set()
        self._scene: Scene | None = None
        self._dynamic_entity_ids: set[str] = set()

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def active(self) -> bool:
        return bool(self._states)

    @property
    def tracked(self) -> tuple[Hashable, ...]:
        return tuple(self._states)

    @property
    def dynamic_entity_ids(self) -> frozenset[str]:
        """Entity IDs whose transform snapshots changed after initial capture."""
        return frozenset(self._dynamic_entity_ids)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._states

    def begin_tick(self) -> int:
        """Open one fixed simulation tick and return its monotonically increasing ID."""

        if self._tick_open:
            raise RuntimeError("an interpolation tick is already open")
        self._tick += 1
        self._tick_open = True
        self._seen.clear()
        return self._tick

    def capture(
        self,
        key: Hashable,
        transform: Transform,
        *,
        parent: Hashable | None = None,
        interpolated: bool = True,
        reset: bool = False,
    ) -> None:
        """Capture one entity's local transform during the current fixed tick."""

        if not self._tick_open:
            raise RuntimeError("capture() requires begin_tick()")
        if parent == key:
            raise ValueError("a transform cannot be its own parent")
        if not isinstance(transform, Transform):
            raise TypeError("transform must be a rendering.Transform")

        state = self._states.get(key)
        if state is None:
            self._states[key] = _State(
                previous=transform,
                current=transform,
                parent=parent,
                interpolated=bool(interpolated),
                last_tick=self._tick,
            )
            self._seen.add(key)
            return

        first_write_this_tick = state.last_tick != self._tick
        state.parent = parent
        state.interpolated = bool(interpolated)

        if reset or state.reset_requested or not state.interpolated:
            state.previous = transform
            state.current = transform
            state.reset_requested = False
        elif first_write_this_tick:
            state.previous = state.current
            state.current = transform
        else:
            # Multiple changes in the same physics tick update only "current".
            state.current = transform

        state.last_tick = self._tick
        self._seen.add(key)

    def capture_scene(self, scene: Scene | None) -> None:
        """Capture changed authoritative local transforms for one fixed tick."""
        if scene is None:
            self.clear()
            return
        if scene is not self._scene:
            self.clear()
            self._scene = scene
            scene._mark_all_transform_entities_dirty()
        changed_entities, removed_entity_ids = scene._take_transform_changes()
        for entity_id in removed_entity_ids:
            self._states.pop(entity_id, None)
            self._dynamic_entity_ids.discard(entity_id)
        self.begin_tick()
        for entity in changed_entities:
            component = entity.get_component(TransformComponent)
            parent = entity.parent_id
            state = self._states.get(entity.entity_id)
            if state is not None and not state.reset_requested and state.parent == parent:
                current = state.current
                if component is not None and component.enabled:
                    unchanged = (
                        state.interpolated
                        and current.position[0] == component.x
                        and current.position[1] == component.y
                        and current.position[2] == 0.0
                        and current.rotation == component.rotation
                        and current.scale[0] == component.scale_x
                        and current.scale[1] == component.scale_y
                        and current.scale[2] == 1.0
                    )
                else:
                    unchanged = (
                        not state.interpolated
                        and current.position == (0.0, 0.0, 0.0)
                        and current.rotation == 0.0
                        and current.scale == (1.0, 1.0, 1.0)
                    )
                if unchanged:
                    self._seen.add(entity.entity_id)
                    continue
            if state is not None:
                self._dynamic_entity_ids.add(entity.entity_id)
            transform = (
                Transform(
                    position=(component.x, component.y, 0.0),
                    rotation=component.rotation,
                    scale=(component.scale_x, component.scale_y, 1.0),
                )
                if component is not None and component.enabled
                else Transform()
            )
            self.capture(
                entity.entity_id,
                transform,
                parent=parent,
                interpolated=component is not None and component.enabled,
            )
        self.end_tick()

    def end_tick(self, *, prune: bool = False) -> None:
        """Close the current tick.

        With ``prune=True``, tracked objects not captured during this tick are
        removed. This is useful when capturing the complete active scene.
        """

        if not self._tick_open:
            raise RuntimeError("no interpolation tick is open")
        if prune:
            for key in tuple(self._states):
                if key not in self._seen:
                    del self._states[key]
        self._tick_open = False
        self._seen.clear()

    def prune_scene(self, scene: Scene | None) -> None:
        """Remove snapshots for entities no longer in the active scene."""
        if scene is None:
            self.clear()
            return
        if scene is not self._scene:
            self.clear()
            self._scene = scene
            scene._mark_all_transform_entities_dirty()
        for entity_id in scene._take_removed_transform_entity_ids():
            self._states.pop(entity_id, None)
            self._dynamic_entity_ids.discard(entity_id)

    def request_reset(self, key: Hashable) -> None:
        """Snap previous/current together on the key's next capture."""

        self._state(key).reset_requested = True
        if self._scene is not None:
            entity = self._scene.find_entity(str(key))
            if entity is not None:
                self._scene._entity_transform_changed(entity)

    def reset(self, key: Hashable, transform: Transform | None = None) -> None:
        """Immediately remove interpolation history for one tracked transform."""

        state = self._state(key)
        value = state.current if transform is None else transform
        if not isinstance(value, Transform):
            raise TypeError("transform must be a rendering.Transform")
        state.previous = value
        state.current = value
        state.reset_requested = False

    def reset_history(self) -> None:
        """Snap every tracked transform to its current simulation value."""
        for state in self._states.values():
            state.previous = state.current
            state.reset_requested = False

    def remove(self, key: Hashable) -> bool:
        removed = self._states.pop(key, None) is not None
        if isinstance(key, str):
            self._dynamic_entity_ids.discard(key)
        return removed

    def clear(self) -> None:
        self._states.clear()
        self._seen.clear()
        self._tick_open = False
        self._scene = None
        self._dynamic_entity_ids.clear()

    def sample_local(self, key: Hashable, fraction: float) -> Transform:
        """Return one local transform sampled between fixed simulation ticks."""

        alpha = _fraction(fraction)
        state = self._state(key)
        if not state.interpolated or state.previous is state.current:
            return state.current
        return _interpolate(state.previous, state.current, alpha)

    def sample_world(self, key: Hashable, fraction: float) -> Transform:
        """Return one sampled transform with tracked parent transforms composed."""

        alpha = _fraction(fraction)
        state = self._state(key)
        if state.parent is None or state.parent not in self._states:
            if not state.interpolated or state.previous is state.current:
                return state.current
            return _interpolate(state.previous, state.current, alpha)
        resolved: dict[Hashable, Transform] = {}
        visiting: set[Hashable] = set()

        def resolve(current_key: Hashable) -> Transform:
            cached = resolved.get(current_key)
            if cached is not None:
                return cached
            if current_key in visiting:
                raise ValueError("transform interpolation hierarchy contains a cycle")

            state = self._state(current_key)
            visiting.add(current_key)
            local = (
                state.current
                if not state.interpolated
                else _interpolate(state.previous, state.current, alpha)
            )

            # Match Scene's tolerant hierarchy behavior: an absent parent is
            # treated as no parent instead of making rendering fail.
            if state.parent is None or state.parent not in self._states:
                result = local
            else:
                result = resolve(state.parent).compose(local)

            visiting.remove(current_key)
            resolved[current_key] = result
            return result

        return resolve(key)

    def sample_all(
        self,
        fraction: float,
        *,
        world: bool = True,
    ) -> dict[Hashable, Transform]:
        """Sample every tracked transform in deterministic insertion order."""

        alpha = _fraction(fraction)
        if world:
            return {key: self.sample_world(key, alpha) for key in self._states}
        return {key: self.sample_local(key, alpha) for key in self._states}

    def _state(self, key: Hashable) -> _State:
        try:
            return self._states[key]
        except KeyError as exc:
            raise KeyError(f"transform is not tracked: {key!r}") from exc
