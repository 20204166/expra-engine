"""Canonical runtime owner for serialized script behaviours."""

from __future__ import annotations

import inspect
from typing import Any

from expra_engine.core.entity import Entity
from expra_engine.filesystem import ResourceId
from expra_engine.runtime.behaviour import Behaviour
from expra_engine.runtime.events import FrameUpdate, SceneStarted, SceneStopped, Update
from expra_engine.runtime.input import ActionEvent
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.runtime.script_registry import ScriptLoadError, ScriptRegistry
from expra_engine.runtime.system import RuntimeSystem


class BehaviourSystem(RuntimeSystem):
    """Instantiate and dispatch every ScriptComponent in runtime scenes."""

    def __init__(self, registry: ScriptRegistry) -> None:
        self.registry = registry
        self.engine: Any = None
        self._instances: dict[tuple[str, str], list[tuple[Entity, Behaviour, ScriptComponent]]] = {}
        self._started_scenes: set[str] = set()
        self._errors: list[ScriptLoadError] = []

    @property
    def instances(self) -> tuple[Behaviour, ...]:
        return tuple(item[1] for values in self._instances.values() for item in values)

    @property
    def errors(self) -> tuple[ScriptLoadError, ...]:
        return tuple(self._errors)

    def start(self, engine: Any) -> None:
        self.engine = engine
        self._errors.clear()
        self._start_scene(engine.active_scene)

    def stop(self) -> None:
        for key in tuple(self._instances):
            self._stop_entity(*key)
        self._started_scenes.clear()
        self.engine = None

    def on_frame_update(self, event: FrameUpdate, signal: Any) -> None:
        for behaviour in self._active_behaviours():
            if behaviour.enabled and behaviour.entity is not None and behaviour.entity.enabled:
                behaviour.on_update(event.time_delta)

    def on_update(self, event: Update, signal: Any) -> None:
        for behaviour in self._active_behaviours():
            if behaviour.enabled and behaviour.entity is not None and behaviour.entity.enabled:
                behaviour.on_fixed_update(event.time_delta)

    def on_action_event(self, event: ActionEvent, signal: Any) -> bool:
        for behaviour in self._active_behaviours():
            if not behaviour.enabled or behaviour.entity is None or not behaviour.entity.enabled:
                continue
            method = behaviour.on_input
            try:
                inspect.signature(method).bind(event)
            except TypeError:
                handled = method(event, signal)
            else:
                handled = method(event)
            if handled:
                return True
        return False

    def on_scene_started(self, event: SceneStarted, signal: Any) -> None:
        if self.engine is not None:
            self._start_scene(self.engine.active_scene)

    def on_scene_stopped(self, event: SceneStopped, signal: Any) -> None:
        if self.engine is not None and self.engine.active_scene is not None:
            self._stop_scene(self.engine.active_scene)

    def reload_script(self, script_id: Any) -> int:
        """Atomically replace live instances for one script resource."""
        resource = script_id if isinstance(script_id, ResourceId) else ResourceId.parse(script_id)
        generation = self.registry.reload(resource)
        replacements: list[
            tuple[tuple[str, str], Entity, Behaviour, Behaviour, ScriptComponent]
        ] = []
        pending: list[tuple[Entity, Behaviour]] = []
        try:
            for key, records in self._instances.items():
                for entity, old, component in records:
                    if component.script_id != resource:
                        continue
                    cls = self.registry.resolve(resource, component.behaviour_class)
                    new = cls()
                    new._system_owned = True
                    schema = cls.exposed_schema()
                    for name, value in component.exposed_values.items():
                        if name in schema:
                            try:
                                setattr(new, name, value)
                            except (AttributeError, TypeError, ValueError):
                                continue
                    new.enabled = component.enabled
                    new._bind_context(
                        input_map=self.engine.input_map,
                        engine=self.engine,
                        scene=self.engine.active_scene,
                        signal=self.engine._eq.signal if self.engine._eq is not None else None,
                    )
                    entity.add_behaviour(new, runtime_factory=cls)
                    try:
                        new._set_started(True)
                        new.on_start()
                    except Exception:
                        entity.remove_behaviour(new)
                        raise
                    pending.append((entity, new))
                    replacements.append((key, entity, old, new, component))
        except Exception:
            for entity, new in pending:
                entity.remove_behaviour(new)
            raise
        for key, entity, old, new, component in replacements:
            try:
                old.on_stop()
            finally:
                old.on_destroy()
                old._destroyed = True
                old._set_started(False)
            entity.remove_behaviour(old)
            records = self._instances[key]
            index = next(i for i, item in enumerate(records) if item[1] is old)
            records[index] = (entity, new, component)
        return generation

    def _start_scene(self, scene: Any) -> None:
        if scene is None:
            return
        if scene.scene_id in self._started_scenes:
            return
        started: list[tuple[str, str]] = []
        self._started_scenes.add(scene.scene_id)
        try:
            for entity in scene.entities:
                components = sorted(
                    (
                        component
                        for component in entity.components
                        if isinstance(component, ScriptComponent)
                    ),
                    key=lambda component: component.order,
                )
                for component in components:
                    try:
                        cls = self.registry.resolve(component.script_id, component.behaviour_class)
                    except ScriptLoadError as exc:
                        self._errors.append(exc)
                        continue
                    behaviour = cls()
                    behaviour._system_owned = True
                    schema = cls.exposed_schema()
                    for name, value in component.exposed_values.items():
                        if name in schema:
                            try:
                                setattr(behaviour, name, value)
                            except (AttributeError, TypeError, ValueError):
                                continue
                    behaviour.enabled = component.enabled
                    entity.add_behaviour(behaviour, runtime_factory=cls)
                    behaviour._bind_context(
                        input_map=self.engine.input_map,
                        engine=self.engine,
                        scene=scene,
                        signal=self.engine._eq.signal if self.engine._eq is not None else None,
                    )
                    behaviour._set_started(True)
                    behaviour.on_start()
                    key = (scene.scene_id, entity.entity_id)
                    self._instances.setdefault(key, []).append((entity, behaviour, component))
                    started.append(key)
        except Exception:
            for scene_id, entity_id in tuple(started):
                self._stop_entity(scene_id, entity_id)
            if "behaviour" in locals() and behaviour.entity is not None:
                if not behaviour._destroyed:
                    behaviour.on_destroy()
                    behaviour._destroyed = True
                entity.remove_behaviour(behaviour)
            self._started_scenes.discard(scene.scene_id)
            raise

    def _stop_scene(self, scene: Any) -> None:
        self._started_scenes.discard(scene.scene_id)
        for entity in scene.entities:
            self._stop_entity(scene.scene_id, entity.entity_id)

    def _stop_entity(self, scene_id: str, entity_id: str) -> None:
        records = self._instances.pop((scene_id, entity_id), ())
        for entity, behaviour, _ in reversed(records):
            try:
                behaviour.on_stop()
            finally:
                if not behaviour._destroyed:
                    behaviour.on_destroy()
                    behaviour._destroyed = True
            behaviour._set_started(False)
            entity.remove_behaviour(behaviour)

    def _active_behaviours(self) -> tuple[Behaviour, ...]:
        active_scene = self.engine.active_scene if self.engine is not None else None
        if active_scene is None:
            return ()
        behaviours: list[Behaviour] = []
        for (scene_id, entity_id), records in tuple(self._instances.items()):
            entity = (
                active_scene.find_entity(entity_id) if scene_id == active_scene.scene_id else None
            )
            if entity is None:
                if scene_id == active_scene.scene_id:
                    self._stop_entity(scene_id, entity_id)
                continue
            behaviours.extend(item[1] for item in records)
        return tuple(behaviours)


__all__ = ["BehaviourSystem"]
