"""Tests for SpatialEditController: move/rotate/scale drag, snap, box-select."""

import unittest
from types import SimpleNamespace
from typing import Any

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene
from expra_engine.editor.commands import Command, CompositeCommand, TransformEntityCommand
from expra_engine.ui.spatial_edit import SpatialEditController, event_extends_selection


class _IdentityCamera:
    """unproject() is the identity -- screen coords double as world coords."""

    def unproject(self, point: tuple[float, float]) -> tuple[float, float]:
        return point


class _FakeCanvas:
    def __init__(self) -> None:
        self.rects: dict[int, tuple[float, float, float, float]] = {}
        self._next_id = 1

    def create_rectangle(self, x0: float, y0: float, x1: float, y1: float, **_kwargs: Any) -> int:
        item_id = self._next_id
        self._next_id += 1
        self.rects[item_id] = (x0, y0, x1, y1)
        return item_id

    def coords(self, item_id: int, x0: float, y0: float, x1: float, y1: float) -> None:
        self.rects[item_id] = (x0, y0, x1, y1)

    def delete(self, item_id: int) -> None:
        self.rects.pop(item_id, None)


def _event(x: float, y: float, state: int = 0) -> Any:
    return SimpleNamespace(x=x, y=y, state=state)


def _make_scene_with_entities(count: int) -> tuple[Scene, list[str]]:
    scene = Scene("test")
    ids = []
    for i in range(count):
        entity = scene.create_entity(f"e{i}")
        entity.add_component(TransformComponent(x=float(i) * 10.0, y=0.0))
        ids.append(entity.entity_id)
    return scene, ids


class _Harness:
    """Builds a SpatialEditController with a mutable selection and a push-log."""

    def __init__(self, entity_count: int = 1) -> None:
        self.scene, self.ids = _make_scene_with_entities(entity_count)
        self.selected: tuple[str, ...] = tuple(self.ids)
        self.pushed: list[Command] = []
        self.redraws = 0
        self.canvas = _FakeCanvas()
        self.controller = SpatialEditController(
            camera=_IdentityCamera(),
            canvas=self.canvas,
            get_scene=lambda: self.scene,
            get_selected_ids=lambda: self.selected,
            push_command=self.pushed.append,
            request_redraw=self._on_redraw,
        )

    def _on_redraw(self) -> None:
        self.redraws += 1

    def transform_of(self, entity_id: str) -> tuple[float, float, float, float, float]:
        entity = self.scene.find_entity(entity_id)
        assert entity is not None
        t = entity.get_component(TransformComponent)
        assert t is not None
        return (t.x, t.y, t.rotation, t.scale_x, t.scale_y)


class MoveDragTests(unittest.TestCase):
    def test_single_entity_drag_produces_one_command_after_multiple_motion_events(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        for step in range(1, 6):
            h.controller.continue_drag(_event(float(step), 0.0))
        h.controller.end_drag()

        self.assertEqual(len(h.pushed), 1)
        self.assertIsInstance(h.pushed[0], TransformEntityCommand)
        self.assertEqual(h.transform_of(h.ids[0])[0], 5.0)  # 0 + final dx=5
        self.assertGreater(h.redraws, 0)

    def test_multi_entity_drag_produces_one_composite_command_and_moves_all(self) -> None:
        h = _Harness(entity_count=3)
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.continue_drag(_event(4.0, 3.0))
        h.controller.end_drag()

        self.assertEqual(len(h.pushed), 1)
        self.assertIsInstance(h.pushed[0], CompositeCommand)
        for i, entity_id in enumerate(h.ids):
            x, y, *_ = h.transform_of(entity_id)
            self.assertAlmostEqual(x, i * 10.0 + 4.0)
            self.assertAlmostEqual(y, 3.0)

    def test_undo_restores_original_positions(self) -> None:
        from expra_engine.editor.commands import CommandStack

        h = _Harness(entity_count=2)
        stack = CommandStack()
        h.controller = SpatialEditController(
            camera=_IdentityCamera(),
            canvas=h.canvas,
            get_scene=lambda: h.scene,
            get_selected_ids=lambda: h.selected,
            push_command=stack.push,
            request_redraw=lambda: None,
        )
        originals = [h.transform_of(eid) for eid in h.ids]
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.continue_drag(_event(7.0, -2.0))
        h.controller.end_drag()
        stack.undo()
        for eid, original in zip(h.ids, originals, strict=True):
            self.assertEqual(h.transform_of(eid), original)

    def test_drag_starting_off_selection_does_nothing(self) -> None:
        h = _Harness(entity_count=1)
        h.selected = ()  # nothing selected
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        self.assertFalse(h.controller.is_dragging_transform)

    def test_zero_movement_click_pushes_no_command(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.end_drag()
        self.assertEqual(h.pushed, [])

    def test_escape_cancels_drag_and_restores_transform_without_pushing(self) -> None:
        h = _Harness(entity_count=1)
        original = h.transform_of(h.ids[0])
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.continue_drag(_event(50.0, 50.0))
        self.assertNotEqual(h.transform_of(h.ids[0]), original)
        h.controller.cancel_drag()
        self.assertEqual(h.transform_of(h.ids[0]), original)
        self.assertEqual(h.pushed, [])
        self.assertFalse(h.controller.is_dragging_transform)


class RotateScaleDragTests(unittest.TestCase):
    def test_alt_drag_rotates_selection_and_own_rotation(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_drag_on_entity(h.ids[0], _event(10.0, 0.0, state=0x0008))  # Alt
        h.controller.continue_drag(_event(0.0, 10.0, state=0x0008))  # 90 degree sweep
        h.controller.end_drag()
        x, y, rotation, _sx, _sy = h.transform_of(h.ids[0])
        self.assertAlmostEqual(rotation, 90.0, places=3)
        # Single-entity rotation is around its own position: position unchanged.
        self.assertAlmostEqual(x, 0.0, places=3)
        self.assertAlmostEqual(y, 0.0, places=3)

    def test_alt_shift_drag_scales_selection_uniformly(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_drag_on_entity(h.ids[0], _event(10.0, 0.0, state=0x0008 | 0x0001))
        h.controller.continue_drag(_event(20.0, 0.0, state=0x0008 | 0x0001))  # 2x distance
        h.controller.end_drag()
        _x, _y, _rot, sx, sy = h.transform_of(h.ids[0])
        self.assertAlmostEqual(sx, 2.0, places=3)
        self.assertAlmostEqual(sy, 2.0, places=3)


class SnapTests(unittest.TestCase):
    def test_grid_snap_rounds_committed_position(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.grid_snap_enabled = True
        h.controller.grid_size = 5.0
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.continue_drag(_event(7.0, 0.0))  # lands on x=7, should snap to 5
        h.controller.end_drag()
        self.assertAlmostEqual(h.transform_of(h.ids[0])[0], 5.0)

    def test_rotation_snap_rounds_committed_rotation(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.rotation_snap_enabled = True
        h.controller.rotation_step_degrees = 15.0
        h.controller.begin_drag_on_entity(h.ids[0], _event(10.0, 0.0, state=0x0008))
        # atan2(4, 10) ~= 21.8 degrees of sweep -- not already a multiple of
        # 15, so this genuinely exercises rounding rather than a coincidence.
        h.controller.continue_drag(_event(10.0, 4.0, state=0x0008))
        h.controller.end_drag()
        self.assertAlmostEqual(h.transform_of(h.ids[0])[2], 15.0, delta=0.01)


class BoxSelectTests(unittest.TestCase):
    def test_tiny_drag_is_treated_as_a_click_not_a_box_select(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_box_select(_event(0.0, 0.0))
        h.controller.continue_box_select(_event(1.0, 1.0))
        rect = h.controller.end_box_select()
        self.assertIsNone(rect)

    def test_real_drag_returns_normalized_rect_and_draws_then_removes_marquee(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_box_select(_event(10.0, 10.0))
        h.controller.continue_box_select(_event(0.0, 0.0))
        self.assertEqual(len(h.canvas.rects), 1)
        rect = h.controller.end_box_select()
        self.assertEqual(rect, (0.0, 0.0, 10.0, 10.0))
        self.assertEqual(h.canvas.rects, {})

    def test_box_select_does_not_start_while_a_transform_drag_is_active(self) -> None:
        h = _Harness(entity_count=1)
        h.controller.begin_drag_on_entity(h.ids[0], _event(0.0, 0.0))
        h.controller.begin_box_select(_event(5.0, 5.0))
        self.assertTrue(h.controller.is_dragging_transform)


class EventExtendsSelectionTests(unittest.TestCase):
    def test_shift_and_control_report_extend(self) -> None:
        self.assertTrue(event_extends_selection(_event(0, 0, state=0x0001)))
        self.assertTrue(event_extends_selection(_event(0, 0, state=0x0004)))

    def test_plain_click_does_not_extend(self) -> None:
        self.assertFalse(event_extends_selection(_event(0, 0, state=0)))


if __name__ == "__main__":
    unittest.main()
