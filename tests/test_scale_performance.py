"""Phase H scale/performance tests: structural scale (spec section 32),
many-instance scale (spec section 33), and rapid-interaction stress (spec
section 41 PERFORMANCE list).

Real numbers measured while writing this file (informational, not asserted
exactly -- see each test's own bound):

  Scene.walk_hierarchy() BEFORE the children_of() derived-index fix:
      n=100: 0.34ms   n=500: 8.44ms   n=1000: 32.25ms   (super-linear)
  AFTER the fix:
      n=100: 0.07ms   n=500: 0.29ms   n=1000: 0.63ms    (linear)

  HierarchyPanel.render() re-render, BEFORE both fixes (children_of index +
  the entity_ids O(n^2) rebuild bug in hierarchy.py):
      n=100: 1.63ms   n=500: 18.62ms   n=1000: 72.60ms
  AFTER both fixes:
      n=100: 1.69ms   n=500: 8.77ms    n=1000: 25.75ms

Neither fix is exercised directly by exact-timing assertions here (timing is
inherently noisy); the growth-shape assertions below are what actually pin
the fix down as a regression guard.
"""

from __future__ import annotations

import time
import unittest
from collections.abc import Callable

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine
from expra_engine.core.scene import (
    Scene,
    SceneInstanceComponent,
    resolve_scene_instances,
)
from expra_engine.editor.commands import Command, CommandStack
from expra_engine.ui.spatial_edit import SpatialEditController
from tests.support.tk_display import display_available

DISPLAY_AVAILABLE = display_available()


def _build_hierarchy(n: int, group_size: int = 5) -> Scene:
    """A mix of parent groups + children, not n flat roots -- exercises
    children_of()/walk_hierarchy() the way a real level actually would.
    """
    scene = Scene("bench")
    count = 0
    while count < n:
        group = scene.create_entity(f"group{count}")
        group.add_component(TransformComponent(x=float(count), y=0.0))
        count += 1
        for j in range(group_size):
            if count >= n:
                break
            child = scene.create_entity(f"child{count}", parent_id=group.entity_id)
            child.add_component(TransformComponent(x=float(j), y=1.0))
            count += 1
    return scene


def _best_of(action: Callable[[], object], repeats: int = 5) -> float:
    """Fastest wall-clock seconds over ``repeats`` runs of ``action``.

    These are sub-millisecond micro-benchmarks; a single sample under a loaded
    machine is noise-dominated. The minimum is a far more stable estimate of
    the true cost, and a genuine complexity regression still shows up because
    every sample gets slow.
    """
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        best = min(best, time.perf_counter() - start)
    return best


class StructuralScaleTests(unittest.TestCase):
    """Spec section 32: 100/500/1000-entity scenes must not degrade quadratically."""

    def test_walk_hierarchy_scales_linearly_not_quadratically(self) -> None:
        timings: dict[int, float] = {}
        for n in (100, 500, 1000, 2000):
            scene = _build_hierarchy(n)
            self.assertEqual(len(scene.walk_hierarchy()), n)
            timings[n] = _best_of(scene.walk_hierarchy)

        # A doubling of n should roughly double the cost (linear), not
        # roughly quadruple it (quadratic). Generous 3x slack per doubling
        # so this isn't flaky on a loaded CI box -- it exists specifically
        # to catch a REGRESSION back to O(n^2), not to enforce a tight bound.
        ratio_500_1000 = timings[1000] / max(timings[500], 1e-6)
        ratio_1000_2000 = timings[2000] / max(timings[1000], 1e-6)
        self.assertLess(ratio_500_1000, 3.0, f"walk_hierarchy timings: {timings}")
        self.assertLess(ratio_1000_2000, 3.0, f"walk_hierarchy timings: {timings}")

    def test_children_of_returns_a_fresh_list_never_the_cached_one(self) -> None:
        """The derived index must never let a caller mutate cached state."""
        scene = _build_hierarchy(20)
        root = scene.roots()[0]
        first = scene.children_of(root.entity_id)
        first.append(root)  # mutate the returned list
        second = scene.children_of(root.entity_id)
        self.assertNotIn(root, second)

    def test_children_index_stays_correct_across_every_mutation_path(self) -> None:
        """Every place that changes scene structure must invalidate the
        derived index -- add_entity, both remove_entity branches,
        set_entity_parent, and clone_entity (via add_entity).
        """
        scene = Scene("t")
        a = scene.create_entity("A")
        b = scene.create_entity("B", parent_id=a.entity_id)
        self.assertEqual([e.entity_id for e in scene.children_of(a.entity_id)], [b.entity_id])

        c = scene.create_entity("C", parent_id=a.entity_id)
        self.assertEqual(
            {e.entity_id for e in scene.children_of(a.entity_id)}, {b.entity_id, c.entity_id}
        )

        scene.remove_entity(c.entity_id)
        self.assertEqual([e.entity_id for e in scene.children_of(a.entity_id)], [b.entity_id])

        d = scene.create_entity("D")
        scene.set_entity_parent(b.entity_id, d.entity_id)
        self.assertEqual(scene.children_of(a.entity_id), [])
        self.assertEqual([e.entity_id for e in scene.children_of(d.entity_id)], [b.entity_id])

        clone = scene.clone_entity(d.entity_id, recursive=True)
        assert clone is not None
        self.assertEqual(len(scene.children_of(clone.entity_id)), 1)

        scene.remove_entity(d.entity_id, recursive=True)
        self.assertEqual(scene.find_entity(b.entity_id), None)
        self.assertEqual(scene.children_of(d.entity_id), [])

    def test_to_dict_from_dict_round_trip_scales_linearly(self) -> None:
        timings: dict[int, float] = {}
        for n in (100, 1000):
            scene = _build_hierarchy(n)

            def round_trip(s: Scene = scene) -> None:
                Scene.from_dict(s.to_dict())

            timings[n] = _best_of(round_trip)
        # 10x entities should cost well under 10x*10 = 100x (a real quadratic
        # blowup would be ~100x); generous guard against a regression.
        self.assertLess(timings[1000] / max(timings[100], 1e-6), 40.0, timings)

    def test_reparent_and_cycle_detection_at_scale(self) -> None:
        """set_entity_parent's cycle check walks to root -- depth matters
        more than breadth here, so build one deep chain among the noise.
        """
        scene = _build_hierarchy(500)
        chain_root = scene.create_entity("chain0")
        previous = chain_root
        for i in range(1, 100):
            previous = scene.create_entity(f"chain{i}", parent_id=previous.entity_id)
        deepest = previous

        start = time.perf_counter()
        with self.assertRaises(ValueError):
            scene.set_entity_parent(chain_root.entity_id, deepest.entity_id)
        duration = time.perf_counter() - start
        self.assertLess(duration, 0.5, "cycle detection on a 100-deep chain took too long")

        new_root = scene.create_entity("new_root")
        scene.set_entity_parent(chain_root.entity_id, new_root.entity_id)
        self.assertEqual(chain_root.parent_id, new_root.entity_id)


class InstanceScaleTests(unittest.TestCase):
    """Spec section 33: many reusable scene instances must preserve source
    identity rather than expanding every instance into duplicated persisted
    JSON."""

    _SOURCE_CHILDREN = 8

    @classmethod
    def _source_scene(cls) -> Scene:
        source = Scene("door_source")
        root = source.create_entity("Door")
        for i in range(cls._SOURCE_CHILDREN):
            child = source.create_entity(f"Panel{i}", parent_id=root.entity_id)
            child.add_component(TransformComponent(x=float(i), y=0.0))
        return source

    @staticmethod
    def _owning_with_instances(count: int) -> Scene:
        owning = Scene("level")
        for i in range(count):
            root = owning.create_entity(f"Instance{i}")
            root.add_component(SceneInstanceComponent("scenes/door.json"))
        return owning

    def test_persisted_form_stays_bounded_with_many_instances(self) -> None:
        count = 100
        # Each instance contributes its own root + a full materialized copy of
        # the source (source root + children).
        per_instance = 2 + self._SOURCE_CHILDREN
        source = self._source_scene()
        owning = self._owning_with_instances(count)

        self.assertEqual(len(owning.to_dict(include_instance_content=False)["entities"]), count)

        resolve_scene_instances(owning, resolve_source=lambda _path: source)

        # In memory every instance materialized its own full copy...
        self.assertEqual(len(owning.entities), count * per_instance)
        # ...but the persisted source-identity form is still one root per
        # instance: 100 instances did NOT add 100 full copies to the file.
        self.assertEqual(len(owning.to_dict(include_instance_content=False)["entities"]), count)
        # Sanity: the full snapshot genuinely holds the expanded content, so
        # the compact form is really saving that duplication.
        self.assertEqual(
            len(owning.to_dict(include_instance_content=True)["entities"]), count * per_instance
        )

    def test_each_instance_root_keeps_its_own_source_reference(self) -> None:
        count = 60
        owning = self._owning_with_instances(count)
        roots = owning.entities
        self.assertEqual(len(roots), count)
        for entity in roots:
            component = entity.get_component(SceneInstanceComponent)
            self.assertIsNotNone(component)
            assert component is not None
            self.assertEqual(component.source_path, "scenes/door.json")

    def test_many_instance_resolution_scales_linearly(self) -> None:
        source = self._source_scene()
        per_instance = 2 + self._SOURCE_CHILDREN
        timings: dict[int, float] = {}
        for count in (25, 100, 400):
            best = float("inf")
            entities = 0
            for _ in range(3):
                owning = self._owning_with_instances(count)
                start = time.perf_counter()
                resolve_scene_instances(owning, resolve_source=lambda _path: source)
                best = min(best, time.perf_counter() - start)
                entities = len(owning.entities)
            timings[count] = best
            self.assertEqual(entities, count * per_instance)
        # 4x the instances should cost far less than 16x (quadratic); 3x slack
        # per step guards a real O(n^2) regression without being flaky.
        self.assertLess(timings[400] / max(timings[100], 1e-6), 12.0, timings)


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class HierarchyPanelScaleTests(unittest.TestCase):
    def test_render_scales_linearly_and_does_not_leak_stale_ids_across_scenes(self) -> None:
        import tkinter as tk

        from expra_engine.ui.hierarchy import HierarchyPanel

        root = tk.Tk()
        try:
            panel = HierarchyPanel(root)
            timings: dict[int, float] = {}
            for n in (100, 500, 1000):
                scene = _build_hierarchy(n)
                panel.render(scene)
                root.update()

                def re_render(s: Scene = scene) -> None:
                    panel.render(s)  # re-render (retained-widget diff path)
                    root.update()

                timings[n] = _best_of(re_render, repeats=3)
                self.assertEqual(len(panel._entity_ids), n)

            ratio = timings[1000] / max(timings[500], 1e-6)
            self.assertLess(ratio, 4.0, f"HierarchyPanel.render() timings: {timings}")

            # Regression guard for the entity_ids bookkeeping bug: repeatedly
            # switching between two small disjoint scenes must not grow
            # self._entity_ids beyond the currently-rendered scene's size.
            scene_a = _build_hierarchy(50)
            scene_b = _build_hierarchy(50)
            for _ in range(30):
                panel.render(scene_a)
                panel.render(scene_b)
            self.assertEqual(len(panel._entity_ids), 50)
        finally:
            root.destroy()


@unittest.skipUnless(DISPLAY_AVAILABLE, "no display for real Tk editor tests")
class RapidSelectionStressTests(unittest.TestCase):
    """Spec section 41 PERFORMANCE: rapid selection over a large hierarchy must
    stay bounded and leave selection bookkeeping exact."""

    def test_rapid_selection_over_large_scene_stays_bounded(self) -> None:
        import tkinter as tk

        from expra_engine.ui.hierarchy import HierarchyPanel

        root = tk.Tk()
        try:
            panel = HierarchyPanel(root)
            scene = _build_hierarchy(1000)
            panel.render(scene)
            root.update()
            ids = [entity.entity_id for entity in scene.entities]
            self.assertEqual(len(ids), 1000)

            start = time.perf_counter()
            for i in range(0, len(ids), 10):  # 100 single selections
                panel.select(ids[i])
            for i in range(0, len(ids), 50):  # 20 multi-selections of 50
                panel.select_many(tuple(ids[i : i + 50]))
            duration = time.perf_counter() - start
            root.update()

            # The last select_many was ids[950:1000].
            self.assertEqual(len(panel._selected_ids), 50)
            self.assertLess(duration, 3.0, f"rapid selection timings: {duration:.3f}s")
        finally:
            root.destroy()


class CommandStackStressTests(unittest.TestCase):
    class _NoopCommand(Command):
        def __init__(self, marker: int) -> None:
            self.marker = marker
            self.executed = 0
            self.undone = 0

        def execute(self) -> None:
            self.executed += 1

        def undo(self) -> None:
            self.undone += 1

    def test_bound_holds_far_past_max_size(self) -> None:
        stack = CommandStack(max_size=200)
        commands = [self._NoopCommand(i) for i in range(500)]
        for command in commands:
            stack.push(command)
        self.assertEqual(len(stack.history), 200)
        self.assertTrue(stack.can_undo)
        # Oldest 300 were discarded; newest 200 remain, in order.
        self.assertEqual(stack.history[0].marker, 300)  # type: ignore[attr-defined]
        self.assertEqual(stack.history[-1].marker, 499)  # type: ignore[attr-defined]

    def test_100_undo_redo_cycles_produce_no_drift_or_growth(self) -> None:
        stack = CommandStack(max_size=200)
        for i in range(200):
            stack.push(self._NoopCommand(i))
        history_len_before = len(stack.history)

        for _ in range(100):
            undone = stack.undo()
            self.assertIsNotNone(undone)
            redone = stack.redo()
            self.assertIs(redone, undone)

        self.assertEqual(len(stack.history), history_len_before)
        self.assertFalse(stack.can_redo)
        self.assertTrue(stack.can_undo)


class DragStressTests(unittest.TestCase):
    class _IdentityCamera:
        def unproject(self, point: tuple[float, float]) -> tuple[float, float]:
            return point

    class _FakeCanvas:
        def create_rectangle(self, *_args: object, **_kwargs: object) -> int:
            return 1

        def coords(self, *_args: object) -> None:
            return None

        def delete(self, *_args: object) -> None:
            return None

    def test_300_drag_gestures_each_collapse_to_exactly_one_command(self) -> None:
        scene = Scene("t")
        entity = scene.create_entity("e0")
        entity.add_component(TransformComponent(x=0.0, y=0.0))
        pushed: list[Command] = []
        controller = SpatialEditController(
            camera=self._IdentityCamera(),
            canvas=self._FakeCanvas(),
            get_scene=lambda: scene,
            get_selected_ids=lambda: (entity.entity_id,),
            push_command=pushed.append,
            request_redraw=lambda: None,
        )
        from types import SimpleNamespace

        start = time.perf_counter()
        for _ in range(300):
            controller.begin_drag_on_entity(
                entity.entity_id, SimpleNamespace(x=0.0, y=0.0, state=0)
            )
            for step in range(5):
                controller.continue_drag(SimpleNamespace(x=float(step), y=float(step), state=0))
            controller.end_drag()
        duration = time.perf_counter() - start

        self.assertEqual(len(pushed), 300)
        self.assertLess(duration, 2.0, "300 drag gestures took unexpectedly long")


class PlayStopStressTests(unittest.TestCase):
    def test_50_play_stop_cycles_leave_edit_scene_byte_identical(self) -> None:
        import json
        from pathlib import Path

        from expra_engine.core.project import Project

        project = Project.load(Path(__file__).parents[1] / "examples" / "blacksite_relay")
        scene = project.load_scene()
        engine = Engine()
        engine.set_project(project)
        engine.set_scene(scene)

        before = json.dumps(engine.edit_scene.to_dict(), sort_keys=True)  # type: ignore[union-attr]
        systems_before = len(engine._systems)

        start = time.perf_counter()
        for _ in range(50):
            engine.play()
            engine.tick(0.016)
            engine.stop()
        duration = time.perf_counter() - start

        after = json.dumps(engine.edit_scene.to_dict(), sort_keys=True)  # type: ignore[union-attr]
        self.assertEqual(before, after)
        self.assertEqual(len(engine._systems), systems_before)
        self.assertLess(duration, 10.0, "50 Play/Stop cycles took unexpectedly long")


if __name__ == "__main__":
    unittest.main()
