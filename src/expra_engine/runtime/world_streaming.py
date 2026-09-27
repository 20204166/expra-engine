"""Bounded World-Level residency state owned by the runtime thread."""

from __future__ import annotations

import contextlib
import copy
import queue
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level, Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.level_anchor import (
    WorldPersistentActorComponent,
)
from expra_engine.runtime.system import RuntimeSystem
from expra_engine.runtime.world_anchors import WorldAnchorPolicyMixin
from expra_engine.runtime.world_camera import WorldCameraContextMixin
from expra_engine.runtime.world_geometry import (
    _descriptor_world_bounds,
    _level_world_bounds,
)
from expra_engine.runtime.world_materialize import (
    _deliver_level_result,
    _LoadCompletion,
    _materialize_world_level,
    _PreparedWorldLevel,
    _session_owned_entity_ids,
)
from expra_engine.runtime.world_policy import (
    LevelResidencyManager,
    LevelResidencySnapshot,
    LevelResidencyState,
    PendingWorldTransition,
    ResidencyCapacityError,
    StreamingAnchor,
    StreamingDecision,
    WorldCameraContext,
    WorldStreamingPolicy,
    WorldStreamingSnapshot,
)
from expra_engine.runtime.world_state import (
    WorldSessionPersistenceMixin,
    WorldSessionState,
    WorldSessionStateError,
)
from expra_engine.runtime.world_transition import (
    WorldTransitionController,
    WorldTransitionSnapshot,
    WorldTraversalMixin,
)

if TYPE_CHECKING:
    from expra_engine.core.project import Project

__all__ = (
    "LevelResidencyManager",
    "LevelResidencySnapshot",
    "LevelResidencyState",
    "ResidencyCapacityError",
    "StreamingAnchor",
    "StreamingDecision",
    "WorldCameraContext",
    "WorldStreamingPolicy",
    "WorldStreamingSnapshot",
    "WorldStreamingSystem",
)


class WorldStreamingSystem(
    WorldAnchorPolicyMixin,
    WorldCameraContextMixin,
    WorldSessionPersistenceMixin,
    WorldTraversalMixin,
    RuntimeSystem,
):
    """Bounded asynchronous Level preparation with owner-thread publication.

    Workers use Project's pure document reader and return detached Level data.
    They only enqueue immutable completions; ``update`` is the sole place that
    mutates residency or publishes a prepared Level to the runtime.
    """

    def __init__(
        self,
        project: Project | None,
        world: World,
        *,
        loader: Callable[[LevelDescriptor], Level] | None = None,
        materializer: Callable[..., Level] | None = None,
        executor_factory: Callable[[int], Executor] | None = None,
        observer: ObservabilityWatcher | None = None,
        world_resource_path: str | None = None,
    ) -> None:
        if not isinstance(world, World):
            raise TypeError("world must be a World document")
        if loader is None and project is None:
            raise ValueError("World streaming requires a Project or Level loader")
        self.project = project
        self.world = world
        self.world_resource_path = world_resource_path
        self._descriptors = {item.instance_id: item for item in world.levels}
        self._residency = LevelResidencyManager(
            tuple(self._descriptors),
            max_resident_levels=world.streaming.max_loaded_levels,
        )
        if loader is None:
            assert project is not None

            def load_from_project(descriptor: LevelDescriptor) -> Level:
                document = project.read_document(descriptor.resource_path, observer=observer)
                if not isinstance(document, Level):
                    raise ValueError(
                        f"World resource {descriptor.resource_path!r} did not contain a Level"
                    )
                return document

            self._loader = load_from_project
        else:
            self._loader = loader
        self._materializer = materializer or (
            lambda level, descriptor, world_id: _materialize_world_level(
                level, descriptor, world_id=world_id
            )
        )
        self._executor_factory = executor_factory or (
            lambda workers: ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="expra-world"
            )
        )
        self._observer = observer
        self._policy = WorldStreamingPolicy()
        self._pinned_levels: set[str] = set()
        self._last_decision = StreamingDecision((), (), (), ())
        self._last_transition: tuple[str, str, str] | None = None
        self._last_transition_error: str | None = None
        self._last_safe_anchor_positions: dict[str, tuple[float, float]] = {}
        self._handover_holds: dict[str, int] = {}
        self._new_handover_sources: set[str] = set()
        self._pending_transitions: dict[str, PendingWorldTransition] = {}
        self._transition_controller = WorldTransitionController()
        self._active_transition_anchor_id: str | None = None
        self.runtime_scene = Scene(
            f"World {world.name}",
            scene_id=str(uuid.uuid4()),
        )
        self._runtime_levels: dict[str, Level] = {}
        self._runtime_entity_ids: dict[str, tuple[str, ...]] = {}
        self._environment_context_level_id: str | None = None
        self._environment_entity_ids: frozenset[str] = frozenset()
        self._persistent_actor_roots: dict[str, str] = {}
        self._persistent_actor_entity_ids: dict[str, tuple[str, ...]] = {}
        self._persistent_actor_sources: dict[str, str] = {}
        self._persistent_actor_source_levels: dict[str, str] = {}
        self._persistent_actor_levels: dict[str, str] = {}
        self._level_streaming_anchor_ids: dict[str, tuple[str, ...]] = {}
        self._level_portal_entity_ids: dict[str, tuple[str, ...]] = {}
        self._persistent_streaming_anchor_owners: dict[str, str] = {}
        self._persistent_portal_owners: dict[str, str] = {}
        self._external_anchors: dict[str, StreamingAnchor] = {}
        self._session_state = WorldSessionState(world.world_id)
        self._session_state.world_resource = world_resource_path
        self._last_session_error: str | None = None
        self._camera_initialized = False
        self._camera_context_level_id: str | None = None
        self._camera_recenter_generation = 0
        self._camera_position: tuple[float, float] | None = None
        self._camera_view_size: tuple[float, float] = (0.0, 0.0)
        self._level_camera_bounds: dict[str, tuple[float, float, float, float] | None] = {
            item.instance_id: _descriptor_world_bounds(item) for item in world.levels
        }
        self._executor: Executor | None = None
        self._owner_thread: int | None = None
        self._engine: Any = None
        self._started = False
        self._closed = False
        self._pending: dict[str, tuple[int, int]] = {}
        self._futures: dict[str, tuple[int, Future[_PreparedWorldLevel]]] = {}
        self._prepared_levels: dict[str, tuple[int, Level]] = {}
        self._authored_levels: dict[str, Level] = {}
        self._authored_state_entity_ids: dict[str, tuple[str, ...]] = {}
        self._manual_requests: set[str] = set()
        self._completions: queue.SimpleQueue[_LoadCompletion] = queue.SimpleQueue()
        self._stale_results_discarded = 0
        self._startup_level_id = world.initial_level_id
        self._persistent_bootstrap_level_ids: set[str] = set()

    def start(self, engine: Any) -> None:
        if self._closed:
            raise RuntimeError("WorldStreamingSystem is closed")
        if self._started:
            raise RuntimeError("WorldStreamingSystem is already started")
        self._owner_thread = threading.get_ident()
        self._engine = engine
        if self._executor is None:
            self._executor = self._executor_factory(self.world.streaming.max_concurrent_loads)
        self._started = True
        primary_anchor_id = self.world.primary_anchor_id
        saved_primary = (
            self._session_state.current_levels.get(primary_anchor_id)
            if primary_anchor_id is not None
            else None
        )
        self._startup_level_id = saved_primary or self.world.initial_level_id
        self._persistent_bootstrap_level_ids = {
            str(snapshot["source_level_id"])
            for snapshot in self._session_state.persistent_actors.values()
            if isinstance(snapshot, dict)
            and isinstance(snapshot.get("source_level_id"), str)
            and snapshot["source_level_id"] in self._descriptors
        }
        required = self._persistent_bootstrap_level_ids | (
            {self._startup_level_id} if self._startup_level_id is not None else set()
        )
        for descriptor in self.world.levels:
            if descriptor.always_loaded or descriptor.instance_id in required:
                priority = descriptor.priority + (
                    1_000_000 if descriptor.instance_id == self._startup_level_id else 500_000
                )
                self._schedule_load(descriptor.instance_id, priority=priority)
        self.update()

    def request_load(self, level_id: str, *, priority: int | None = None) -> int:
        self._assert_owner()
        if level_id not in self._descriptors:
            raise KeyError(f"unknown World Level instance: {level_id!r}")
        self._manual_requests.add(level_id)
        return self._schedule_load(level_id, priority=priority)

    def _schedule_load(self, level_id: str, *, priority: int | None = None) -> int:
        descriptor = self._descriptors.get(level_id)
        if descriptor is None:
            raise KeyError(f"unknown World Level instance: {level_id!r}")
        generation = self._residency.request_load(level_id)
        if self._residency.state(level_id).state is LevelResidencyState.QUEUED:
            self._pending[level_id] = (
                generation,
                descriptor.priority if priority is None else int(priority),
            )
        self._record("request")
        self._pump()
        return generation

    def cancel_load(self, level_id: str) -> bool:
        self._assert_owner()
        if not self._residency.cancel_load(level_id):
            return False
        self._manual_requests.discard(level_id)
        self._pending.pop(level_id, None)
        pending = self._futures.get(level_id)
        if pending is not None and pending[1].cancel():
            self._futures.pop(level_id, None)
        self._record("cancelled")
        self._pump()
        return True

    def update(self) -> None:
        """Apply completed worker results and start only budgeted queued loads."""
        self._assert_owner()
        _obs = self._observer
        _update_token = _obs.begin("world:streaming:update") if _obs is not None else None
        _update_outcome: str = "success"
        try:
            self._update_inner()
        except Exception:
            _update_outcome = "failure"
            raise
        finally:
            if _obs is not None and _update_token is not None:
                _obs.finish(_update_token, outcome=_update_outcome)  # type: ignore[arg-type]

    def _update_inner(self) -> None:
        while True:
            try:
                completion = self._completions.get_nowait()
            except queue.Empty:
                break
            current = self._futures.get(completion.level_id)
            if current is None or current[0] != completion.generation:
                self._discard_stale()
                continue
            self._futures.pop(completion.level_id, None)
            if completion.error is not None:
                if self._residency.fail_load(
                    completion.level_id, completion.generation, completion.error
                ):
                    self._record("failed")
                else:
                    self._discard_stale()
            elif completion.prepared is not None:
                try:
                    _obs = self._observer
                    _rt = _obs.begin("world:state:restore") if _obs is not None else None
                    try:
                        self._session_state.restore_level(
                            completion.level_id, completion.prepared.runtime
                        )
                    except Exception:
                        if _obs is not None and _rt is not None:
                            _obs.finish(_rt, outcome="failure")  # type: ignore[arg-type]
                        raise
                    else:
                        if _obs is not None and _rt is not None:
                            _obs.finish(_rt)  # type: ignore[arg-type]
                    committed = self._residency.complete_load(
                        completion.level_id,
                        completion.generation,
                        completion.prepared.authored,
                    )
                except Exception as error:  # noqa: BLE001 - convert materializer failures to residency state
                    if self._residency.fail_load(completion.level_id, completion.generation, error):
                        if isinstance(error, WorldSessionStateError):
                            self._last_session_error = str(error)[:200]
                        self._record("failed")
                    else:
                        self._discard_stale()
                else:
                    if committed:
                        self._last_session_error = None
                        self._level_camera_bounds[completion.level_id] = _level_world_bounds(
                            completion.prepared.authored,
                            self._descriptors[completion.level_id],
                        )
                        self._prepared_levels[completion.level_id] = (
                            completion.generation,
                            completion.prepared.runtime,
                        )
                        self._authored_levels[completion.level_id] = completion.prepared.authored
                        self._authored_state_entity_ids[completion.level_id] = (
                            _session_owned_entity_ids(completion.prepared.runtime)
                        )
                        self._record("completed")
                        if completion.level_id == self._startup_level_id:
                            self.activate_level(completion.level_id)
                        elif completion.level_id in self._persistent_bootstrap_level_ids:
                            self.activate_level(completion.level_id)
                            self._persistent_bootstrap_level_ids.discard(completion.level_id)
                    else:
                        self._discard_stale()
        self._reconcile_streaming_policy()
        self._pump()

    def on_frame_update(self, event: object, _signal: object) -> None:
        if self._started:
            self.update()
            self._advance_active_transition(float(getattr(event, "time_delta", 0.0)))

    @property
    def transition(self) -> WorldTransitionSnapshot:
        return self._transition_controller.snapshot

    @property
    def transition_alpha(self) -> float:
        return self._transition_controller.alpha

    def activate_level(self, level_id: str) -> bool:
        self._assert_owner()
        current = self._residency.state(level_id)
        if current.state is LevelResidencyState.ACTIVE:
            return False
        if current.state not in {LevelResidencyState.LOADED, LevelResidencyState.DORMANT}:
            return False
        runtime_level = self._runtime_levels.get(level_id)
        if runtime_level is None:
            prepared = self._prepared_levels.get(level_id)
            if not current.has_level or prepared is None or prepared[0] != current.generation:
                return False
            runtime_level = prepared[1]
        persistent_candidates = self._prepare_persistent_entities(level_id, runtime_level)
        added: list[str] = []
        persistent_added: list[str] = []
        initialize_camera = not self._camera_initialized
        previous_camera = copy.deepcopy(self.runtime_scene.camera)
        _obs = self._observer
        _at = _obs.begin("world:level:activate") if _obs is not None else None
        try:
            for _persistent_id, _source_path, _root, entities in persistent_candidates:
                for entity in entities:
                    self.runtime_scene.add_entity(entity)
                    persistent_added.append(entity.entity_id)
            # Entity objects have one Scene owner at a time. The World
            # aggregate owns active Level Entities; the prepared Level
            # wrapper owns them again while dormant.
            moved = runtime_level.transfer_entities_to(self.runtime_scene)
            added.extend(entity.entity_id for entity in moved)
            if initialize_camera:
                self.runtime_scene.camera = copy.deepcopy(runtime_level.camera)
            if not self._residency.activate(level_id):
                raise RuntimeError("Level residency changed before activation committed")
            if self._engine is not None:
                notify = getattr(self._engine, "notify_world_level_activated", None)
                if callable(notify):
                    notify(level_id, (*persistent_added, *added))
        except Exception as error:  # noqa: BLE001 - roll back partial runtime activation
            self._residency.fail_activation(level_id, error)
            for entity_id in reversed(added):
                self.runtime_scene.remove_entity(entity_id)
            for entity_id in reversed(persistent_added):
                self.runtime_scene.remove_entity(entity_id)
            self._runtime_levels.pop(level_id, None)
            self._runtime_entity_ids.pop(level_id, None)
            self._prepared_levels.pop(level_id, None)
            self._authored_levels.pop(level_id, None)
            self._authored_state_entity_ids.pop(level_id, None)
            if initialize_camera:
                self.runtime_scene.camera = previous_camera
            if _obs is not None and _at is not None:
                _obs.finish(_at, outcome="failure")  # type: ignore[arg-type]
            self._record("failed")
            self._last_transition_error = (
                f"Level {level_id!r} activation failed: {type(error).__name__}: {str(error)[:160]}"
            )
            return False
        if _obs is not None and _at is not None:
            _obs.finish(_at)  # type: ignore[arg-type]
        for persistent_id, source_path, root, entities in persistent_candidates:
            self._persistent_actor_roots[persistent_id] = root.entity_id
            self._persistent_actor_entity_ids[persistent_id] = tuple(
                entity.entity_id for entity in entities
            )
            self._persistent_actor_sources[persistent_id] = source_path
            self._persistent_actor_source_levels.setdefault(persistent_id, level_id)
            self._persistent_actor_levels.setdefault(persistent_id, level_id)
        self._runtime_levels[level_id] = runtime_level
        self._runtime_entity_ids[level_id] = tuple(added)
        self._index_level_anchors(level_id, tuple(added), tuple(persistent_added))
        self._prepared_levels.pop(level_id, None)
        if initialize_camera:
            self._camera_initialized = True
            self._camera_context_level_id = level_id
            self._environment_context_level_id = None
            self._environment_entity_ids = frozenset()
        return True

    def deactivate_level(self, level_id: str) -> bool:
        self._assert_owner()
        runtime_level = self._runtime_levels.get(level_id)
        if runtime_level is None:
            return False
        entity_ids = tuple(
            entity_id
            for entity_id in self._runtime_entity_ids.get(level_id, ())
            if self.runtime_scene.find_entity(entity_id) is not None
        )
        if self._engine is not None:
            notify = getattr(self._engine, "notify_world_level_deactivated", None)
            if callable(notify):
                notify(level_id, entity_ids)
        if not self._residency.deactivate(level_id):
            return False
        _obs = self._observer
        _dt = _obs.begin("world:level:deactivate") if _obs is not None else None
        try:
            self.runtime_scene.transfer_entities_to(runtime_level, entity_ids)
        finally:
            if _obs is not None and _dt is not None:
                _obs.finish(_dt)  # type: ignore[arg-type]
        self._runtime_entity_ids.pop(level_id, None)
        self._level_streaming_anchor_ids.pop(level_id, None)
        self._level_portal_entity_ids.pop(level_id, None)
        return True

    def unload_level(self, level_id: str) -> bool:
        self._assert_owner()
        if level_id in self._pinned_levels:
            raise RuntimeError(f"World Level {level_id!r} is pinned; unpin it before unloading")
        self._manual_requests.discard(level_id)
        snapshot = self._residency.state(level_id)
        if snapshot.state is LevelResidencyState.ACTIVE:
            self.deactivate_level(level_id)
        runtime_level = self._runtime_levels.get(level_id)
        if runtime_level is not None:
            _obs = self._observer
            _ct = _obs.begin("world:state:capture") if _obs is not None else None
            try:
                authored_ids = self._authored_state_entity_ids.get(level_id)
                self._session_state.capture_level(
                    level_id,
                    runtime_level,
                    authored_entity_ids=authored_ids,
                )
            except WorldSessionStateError as error:
                if _obs is not None and _ct is not None:
                    _obs.finish(_ct, outcome="failure")  # type: ignore[arg-type]
                self._last_session_error = str(error)[:200]
                return False
            else:
                if _obs is not None and _ct is not None:
                    _obs.finish(_ct)  # type: ignore[arg-type]
            self._last_session_error = None
        _obs = self._observer
        _ul = _obs.begin("world:level:unload") if _obs is not None else None
        try:
            unloaded = self._residency.unload(level_id)
        finally:
            if _obs is not None and _ul is not None:
                _obs.finish(_ul)  # type: ignore[arg-type]
        if unloaded:
            self._runtime_levels.pop(level_id, None)
            self._runtime_entity_ids.pop(level_id, None)
            self._prepared_levels.pop(level_id, None)
            self._authored_levels.pop(level_id, None)
            self._authored_state_entity_ids.pop(level_id, None)
        return unloaded

    def retry_level(self, level_id: str) -> int:
        """Explicitly retry a failed or cancelled Level request."""
        self._assert_owner()
        return self.request_load(level_id)

    def _prepare_persistent_entities(
        self, level_id: str, runtime_level: Level
    ) -> list[tuple[str, str, Entity, tuple[Entity, ...]]]:
        root_ids = {
            entity.entity_id
            for entity in runtime_level.entities
            if entity.has_tag("expra_world_level_root")
        }
        source_path = self._descriptors[level_id].resource_path
        seen: set[str] = set()
        staged: list[tuple[str, str, Entity, tuple[Entity, ...]]] = []
        for entity in tuple(runtime_level.entities):
            marker = entity.get_component(WorldPersistentActorComponent)
            if marker is None:
                continue
            if marker.persistent_id in seen:
                raise ValueError(f"duplicate persistent actor ID: {marker.persistent_id!r}")
            seen.add(marker.persistent_id)
            if entity.parent_id not in root_ids:
                raise ValueError(
                    "World-persistent actor must be a Level root Entity; "
                    "cross-owner parenting is not supported"
                )
            previous_source = self._persistent_actor_sources.get(marker.persistent_id)
            if previous_source is not None:
                if previous_source != source_path:
                    raise ValueError(
                        f"persistent actor ID {marker.persistent_id!r} is declared by multiple Levels"
                    )
                runtime_level.remove_entity(entity.entity_id, recursive=True)
                continue
            subtree = tuple(runtime_level.walk_hierarchy(entity.entity_id))
            pose = runtime_level.world_transform(entity.entity_id)
            transform = entity.get_component(TransformComponent)
            if transform is None:
                entity.add_component(
                    TransformComponent(
                        x=pose.position[0],
                        y=pose.position[1],
                        rotation=pose.rotation,
                        scale_x=pose.scale[0],
                        scale_y=pose.scale[1],
                    )
                )
            else:
                transform.x, transform.y = pose.position
                transform.rotation = pose.rotation
                transform.scale_x, transform.scale_y = pose.scale
            saved_actor_levels = self._session_state.restore_persistent_actor(
                marker.persistent_id, subtree
            )
            if saved_actor_levels is not None and saved_actor_levels[0] != level_id:
                raise WorldSessionStateError(
                    f"persistent actor {marker.persistent_id!r} source Level changed"
                )
            if saved_actor_levels is not None:
                self._persistent_actor_levels[marker.persistent_id] = saved_actor_levels[1]
            entity.parent_id = None
            runtime_level.remove_entity(entity.entity_id, recursive=True)
            staged.append((marker.persistent_id, source_path, entity, subtree))
        return staged

    def state(self, level_id: str) -> LevelResidencySnapshot:
        return self._residency.state(level_id)

    def loaded_levels(self) -> tuple[str, ...]:
        return tuple(
            item.level_id
            for item in self._residency.snapshots()
            if item.state
            in {
                LevelResidencyState.LOADED,
                LevelResidencyState.ACTIVE,
                LevelResidencyState.DORMANT,
            }
        )

    def active_levels(self) -> tuple[str, ...]:
        return tuple(
            item.level_id
            for item in self._residency.snapshots()
            if item.state is LevelResidencyState.ACTIVE
        )

    @property
    def environment_entity_ids(self) -> frozenset[str]:
        """Entities in the active camera-context Level that may supply ambient modulation."""
        level_id = self.camera_context.camera_context_level_id
        if level_id != self._environment_context_level_id:
            self._environment_context_level_id = level_id
            self._environment_entity_ids = frozenset(self._runtime_entity_ids.get(level_id, ()))
        if (
            level_id is None
            or self._residency.state(level_id).state is not LevelResidencyState.ACTIVE
        ):
            return frozenset()
        return self._environment_entity_ids

    def snapshot(self) -> WorldStreamingSnapshot:
        anchors = self.streaming_anchors() if self._started else ()
        return WorldStreamingSnapshot(
            world_id=self.world.world_id,
            levels=self._residency.snapshots(),
            pending_level_ids=tuple(sorted(self._pending)),
            in_flight_level_ids=tuple(sorted(self._futures)),
            stale_results_discarded=self._stale_results_discarded,
            max_concurrent_loads=self.world.streaming.max_concurrent_loads,
            max_resident_levels=self.world.streaming.max_loaded_levels,
            primary_levels=tuple(sorted((anchor.anchor_id, anchor.level_id) for anchor in anchors)),
            residency_reasons=self._last_decision.reasons,
            last_transition=self._last_transition,
            last_transition_error=self._last_transition_error,
            connection_preloads=self._last_decision.preload_level_ids,
            camera=self.camera_context,
            pending_transitions=tuple(
                self._pending_transitions[key] for key in sorted(self._pending_transitions)
            ),
            session_state_counts=tuple(
                (level_id, len(values))
                for level_id, values in sorted(self._session_state.levels.items())
            ),
            last_session_error=self._last_session_error,
            transition=self.transition,
        )

    def stop(self) -> None:
        if not self._started:
            return
        self._assert_owner()
        self._pending.clear()
        self._prepared_levels.clear()
        self._authored_levels.clear()
        self._authored_state_entity_ids.clear()
        for snapshot in self._residency.snapshots():
            if snapshot.state in {LevelResidencyState.QUEUED, LevelResidencyState.LOADING}:
                self._residency.cancel_load(snapshot.level_id)
                self._residency.unload(snapshot.level_id)
            elif snapshot.state is LevelResidencyState.ACTIVE:
                self.deactivate_level(snapshot.level_id)
                self._residency.unload(snapshot.level_id)
                self._runtime_levels.pop(snapshot.level_id, None)
            elif snapshot.state is not LevelResidencyState.UNLOADED:
                self._residency.unload(snapshot.level_id)
                self._runtime_levels.pop(snapshot.level_id, None)
                self._runtime_entity_ids.pop(snapshot.level_id, None)
        persistent_entity_ids = {
            entity_id
            for entity_ids in self._persistent_actor_entity_ids.values()
            for entity_id in entity_ids
        }
        for entity_id in persistent_entity_ids:
            self.runtime_scene.remove_entity(entity_id)
        self._persistent_actor_roots.clear()
        self._persistent_actor_entity_ids.clear()
        self._persistent_actor_sources.clear()
        self._persistent_actor_source_levels.clear()
        self._persistent_actor_levels.clear()
        self._level_streaming_anchor_ids.clear()
        self._level_portal_entity_ids.clear()
        self._persistent_streaming_anchor_owners.clear()
        self._persistent_portal_owners.clear()
        self._session_state.levels.clear()
        self._session_state.deleted_entities.clear()
        self._session_state.persistent_actors.clear()
        self._session_state.current_levels.clear()
        self._last_session_error = None
        self._pinned_levels.clear()
        self._manual_requests.clear()
        self._last_safe_anchor_positions.clear()
        self._handover_holds.clear()
        self._new_handover_sources.clear()
        self._pending_transitions.clear()
        self._transition_controller = WorldTransitionController(
            fade_duration=self._transition_controller.fade_duration
        )
        self._active_transition_anchor_id = None
        self._camera_context_level_id = None
        self._camera_position = None
        self._camera_view_size = (0.0, 0.0)
        self.runtime_scene.camera = {}
        self._camera_initialized = False
        self._persistent_bootstrap_level_ids.clear()
        for _target, future in self._futures.values():
            future.cancel()
        self._started = False
        self._engine = None

    def close(self) -> None:
        """Permanently close the fixed worker pool after invalidating its requests."""
        if self._started:
            self.stop()
        if self._closed:
            return
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _pump(self) -> None:
        executor = self._executor
        if not self._started or executor is None:
            return
        limit = self.world.streaming.max_concurrent_loads
        while self._pending and len(self._futures) < limit:
            level_id = min(
                self._pending,
                key=lambda item: (-self._pending[item][1], item),
            )
            generation, _priority = self._pending.pop(level_id)
            if not self._residency.begin_load(level_id, generation):
                continue
            descriptor = self._descriptors[level_id]
            loader = self._loader
            materializer = self._materializer
            world_id = self.world.world_id
            completion_queue = self._completions
            _obs = self._observer

            def load_level(
                item: LevelDescriptor = descriptor,
                level_loader: Callable[[LevelDescriptor], Level] = loader,
                level_materializer: Callable[..., Level] = materializer,
                active_world_id: str = world_id,
                obs: ObservabilityWatcher | None = _obs,
            ) -> _PreparedWorldLevel:
                _pt = obs.begin("world:level:prepare") if obs is not None else None
                _outcome = "success"
                try:
                    authored = level_loader(item)
                    if not isinstance(authored, Level):
                        raise TypeError("World Level loader must return a Level")
                    runtime = level_materializer(authored, item, world_id=active_world_id)
                    if not isinstance(runtime, Level):
                        raise TypeError("World Level materializer must return a Level")
                    return _PreparedWorldLevel(authored, runtime)
                except Exception:
                    _outcome = "failure"
                    raise
                finally:
                    if obs is not None and _pt is not None:
                        with contextlib.suppress(Exception):
                            obs.finish(_pt, outcome=_outcome)  # type: ignore[arg-type]

            try:
                future = executor.submit(load_level)
            except Exception as error:  # noqa: BLE001 - map executor submission failure to load state
                self._residency.fail_load(level_id, generation, error)
                self._record("failed")
                continue
            self._futures[level_id] = (generation, future)
            future.add_done_callback(
                lambda result, key=level_id, epoch=generation, target=completion_queue: (
                    _deliver_level_result(target, key, epoch, result)
                )
            )
            self._record("started")

    def _discard_stale(self) -> None:
        self._stale_results_discarded += 1
        self._record("stale")

    def _record(self, counter: str) -> None:
        if self._observer is not None:
            with contextlib.suppress(Exception):
                self._observer.increment("world:level:load", counter)

    def _assert_owner(self) -> None:
        if not self._started or self._owner_thread != threading.get_ident():
            raise RuntimeError("World streaming state may only be changed on its owner thread")
