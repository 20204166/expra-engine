"""Integration tests for fixed-tick interpolation through Engine rendering."""

from __future__ import annotations

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import Engine, EngineRunState
from expra_engine.core.scene import Scene
from expra_engine.runtime.events import Update
from expra_engine.runtime.render_extractor import extract_render_frame
from expra_engine.runtime.system import RuntimeSystem
from expra_engine.runtime.visual_components import PrimitiveComponent


class _MoveSystem(RuntimeSystem):
    def start(self, engine: Engine) -> None:
        self.engine = engine

    def on_update(self, event: Update, signal: object) -> None:
        scene = self.engine.active_scene
        if scene is not None:
            transform = scene.entities[0].get_component(TransformComponent)
            assert transform is not None
            transform.x += 10.0


def _engine() -> tuple[Engine, str]:
    engine = Engine()
    scene = Scene("runtime")
    entity = scene.create_entity("moving", entity_id="moving")
    entity.add_component(TransformComponent())
    entity.add_component(PrimitiveComponent("rectangle"))
    engine.set_scene(scene)
    engine.add_system(_MoveSystem())
    return engine, entity.entity_id


def test_fixed_update_flows_through_interpolation_into_render_extraction() -> None:
    engine, entity_id = _engine()
    engine.play()
    engine.tick(1.0 / 60.0 * 1.5)

    frame = extract_render_frame(
        engine.active_scene,
        interpolator=engine.transform_interpolator,
        interpolation_fraction=engine.interpolation_fraction,
    )

    assert frame.items[0].transform.position == pytest.approx((5.0, 0.0, 0.0))


def test_interpolation_state_is_runtime_only_and_stop_start_resets_history() -> None:
    engine, entity_id = _engine()
    engine.play()
    engine.tick(1.0 / 60.0)
    assert entity_id in engine.transform_interpolator
    assert "interpolation" not in engine.active_scene.to_dict()

    engine.stop()
    assert engine.run_state is EngineRunState.EDIT
    assert engine.transform_interpolator.tracked == ()
    engine.play()
    assert engine.transform_interpolator.sample_world(entity_id, 0.5).position == (0.0, 0.0, 0.0)


def test_removed_entities_are_pruned_after_the_fixed_update_boundary() -> None:
    engine, entity_id = _engine()
    engine.play()
    engine.tick(1.0 / 60.0)
    assert entity_id in engine.transform_interpolator
    assert engine.active_scene.remove_entity(entity_id)
    engine.tick(0.0)
    assert entity_id not in engine.transform_interpolator


def test_scene_replacement_does_not_leak_snapshots() -> None:
    engine, entity_id = _engine()
    engine.play()
    engine.tick(1.0 / 60.0)
    replacement = Scene("replacement")
    replacement_entity = replacement.create_entity("replacement", entity_id=entity_id)
    replacement_entity.add_component(TransformComponent(x=100.0))

    engine.replace_scene(replacement)

    assert engine.transform_interpolator.sample_world(entity_id, 0.5).position == (100.0, 0.0, 0.0)


def test_parent_interpolation_composes_rotation_and_scale_before_child_rendering() -> None:
    engine = Engine()
    scene = Scene("hierarchy")
    parent = scene.create_entity("parent", entity_id="parent")
    parent.add_component(TransformComponent(scale_x=1.0, scale_y=1.0))
    child = scene.create_entity("child", entity_id="child", parent_id="parent")
    child.add_component(TransformComponent(x=2.0))
    child.add_component(PrimitiveComponent("rectangle"))
    engine.set_scene(scene)
    engine.play()
    runtime_parent = engine.active_scene.find_entity("parent")
    assert runtime_parent is not None
    runtime_transform = runtime_parent.get_component(TransformComponent)
    assert runtime_transform is not None
    runtime_transform.rotation = 90.0
    runtime_transform.scale_x = 2.0
    runtime_transform.scale_y = 2.0
    engine.tick(1.0 / 60.0)

    frame = extract_render_frame(
        engine.active_scene,
        interpolator=engine.transform_interpolator,
        interpolation_fraction=1.0,
    )

    assert frame.items[0].transform.position == pytest.approx((0.0, 4.0, 0.0), abs=1e-9)


def test_pause_and_resume_snap_interpolation_history_without_render_jump() -> None:
    engine, entity_id = _engine()
    engine.play()
    engine.tick(1.0 / 60.0)
    before_pause = engine.transform_interpolator.sample_world(entity_id, 0.5)

    engine.pause()
    engine.tick(1.0 / 60.0)
    engine.play()

    after_resume = engine.transform_interpolator.sample_world(entity_id, 0.5)
    assert after_resume == engine.transform_interpolator.sample_world(entity_id, 0.0)
    assert after_resume != before_pause


def test_push_and_pop_scene_replace_interpolation_scope() -> None:
    engine, base_id = _engine()
    engine.play()
    overlay = Scene("overlay")
    overlay_entity = overlay.create_entity("overlay", entity_id="overlay")
    overlay_entity.add_component(TransformComponent(x=20.0))

    engine.push_scene(overlay)
    assert engine.transform_interpolator.tracked == ("overlay",)
    engine.pop_scene()

    assert engine.transform_interpolator.tracked == (base_id,)
