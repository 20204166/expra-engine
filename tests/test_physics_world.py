import math

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.physics import TriggerEvent
from expra_engine.runtime.physics_world import PhysicsWorld2D


def make_scene() -> Scene:
    return Scene("physics")


def add_box(scene: Scene, name: str, x: float, y: float, **kwargs):
    entity = scene.create_entity(name)
    entity.add_component(TransformComponent(x=x, y=y))
    entity.add_component(ColliderComponent(width=2.0, height=2.0, **kwargs))
    return entity


def test_collider_validates_supported_geometry_and_serializes_canonically():
    with pytest.raises(ValueError):
        ColliderComponent(width=0.0, height=1.0)
    with pytest.raises(ValueError):
        ColliderComponent(shape="triangle", width=1.0, height=1.0)
    with pytest.raises(ValueError):
        ColliderComponent(shape="circle", radius=math.inf)
    with pytest.raises(ValueError):
        ColliderComponent(width=1.0, height=1.0, radius=0.0)

    collider = ColliderComponent(
        shape="circle",
        radius=2.0,
        offset=(1.0, -2.0),
        solid=False,
        trigger=True,
        layer=4,
        mask=8,
    )
    assert set(collider.to_dict()) == {
        "type", "enabled", "shape", "width", "height", "radius", "offset",
        "solid", "trigger", "layer", "mask",
    }
    assert component_from_dict(collider.to_dict()).to_dict() == collider.to_dict()
    assert collider.editor_outline["offset"] == (1.0, -2.0)
    assert "editor_outline" not in collider.to_dict()
    assert tuple(field.name for field in component_type_spec("collider").fields) == (
        "shape", "width", "height", "radius", "offset", "solid", "trigger", "enabled",
        "layer", "mask",
    )


def test_overlap_includes_exact_edge_contact_and_filters_layers():
    scene = make_scene()
    first = add_box(scene, "first", 0.0, 0.0, layer=1, mask=2)
    second = add_box(scene, "second", 2.0, 0.0, layer=2, mask=1)
    blocked = add_box(scene, "blocked", 0.0, 2.0, layer=4, mask=1)
    world = PhysicsWorld2D(scene)

    assert world.overlap(first.entity_id) == (second.entity_id,)
    assert world.overlap(blocked.entity_id) == ()


def test_raycast_returns_nearest_hit_with_stable_tie_order():
    scene = make_scene()
    first = add_box(scene, "first", 5.0, 0.0)
    second = add_box(scene, "second", 5.0, 0.0)
    world = PhysicsWorld2D(scene)

    result = world.raycast((0.0, 0.0), (1.0, 0.0), 10.0)
    assert result.hit is True
    assert result.entity_id == first.entity_id
    assert result.distance == pytest.approx(4.0)
    assert result.fraction == pytest.approx(0.4)


def test_disabled_and_removed_colliders_are_ignored():
    scene = make_scene()
    first = add_box(scene, "first", 0.0, 0.0, enabled=False)
    second = add_box(scene, "second", 1.0, 0.0)
    world = PhysicsWorld2D(scene)
    assert world.overlap(first.entity_id) == ()
    assert world.raycast((-3.0, 0.0), (1.0, 0.0), 10.0).entity_id == second.entity_id
    scene.remove_entity(second.entity_id)
    assert world.raycast((-3.0, 0.0), (1.0, 0.0), 10.0).hit is False


def test_trigger_lifecycle_reports_enter_stay_exit_and_removed_pairs():
    scene = make_scene()
    trigger = add_box(scene, "trigger", 0.0, 0.0, trigger=True, solid=False)
    body = add_box(scene, "body", 0.5, 0.0)
    world = PhysicsWorld2D(scene)

    assert world.step_triggers() == (
        TriggerEvent("entered", trigger.entity_id, body.entity_id),
    )
    assert world.step_triggers() == (
        TriggerEvent("stayed", trigger.entity_id, body.entity_id),
    )
    scene.remove_entity(body.entity_id)
    assert world.step_triggers() == (
        TriggerEvent("exited", trigger.entity_id, body.entity_id),
    )
    assert world.step_triggers() == ()
