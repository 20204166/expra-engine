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
    add_box(scene, "second", 5.0, 0.0)
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


def test_entity_order_for_removed_entities_is_pruned_after_queries():
    scene = make_scene()
    world = PhysicsWorld2D(scene)

    for index in range(32):
        entity = add_box(scene, f"temporary-{index}", float(index), 0.0)
        world.overlap(entity.entity_id)
        scene.remove_entity(entity.entity_id)

    survivor = add_box(scene, "survivor", 0.0, 0.0)
    world.overlap(survivor.entity_id)

    assert set(world._entity_order) == {survivor.entity_id}


def test_physics_queries_use_hierarchy_composed_world_positions() -> None:
    scene = make_scene()
    level_root = scene.create_entity("Placed Level")
    level_root.add_component(TransformComponent(x=100.0, y=50.0))
    parent = scene.create_entity("Parent", parent_id=level_root.entity_id)
    parent.add_component(TransformComponent(x=2.0, y=3.0))
    body = add_box(scene, "placed-body", 4.0, 5.0)
    body.parent_id = parent.entity_id
    target = add_box(scene, "world-target", 106.0, 58.0)

    world = PhysicsWorld2D(scene)

    assert world.overlap(body.entity_id) == (target.entity_id,)


def test_physics_uses_identity_pose_for_disabled_transform_components() -> None:
    scene = make_scene()
    disabled = scene.create_entity("disabled transform")
    disabled.add_component(TransformComponent(x=100.0, enabled=False))
    disabled.add_component(ColliderComponent(width=2.0, height=2.0))
    nearby = add_box(scene, "nearby", 0.5, 0.0)

    assert PhysicsWorld2D(scene).overlap(disabled.entity_id) == (nearby.entity_id,)


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
