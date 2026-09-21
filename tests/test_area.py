import math

import pytest

from expra_engine.core.component import TransformComponent, component_from_dict
from expra_engine.core.component_schema import component_type_spec
from expra_engine.core.scene import Scene
from expra_engine.runtime.area import AreaComponent, SpaceOverride
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.physics import AreaEffect2D, TriggerEvent
from expra_engine.runtime.physics_world import PhysicsWorld2D


def add_entity(scene: Scene, name: str, x: float, y: float):
    entity = scene.create_entity(name)
    entity.add_component(TransformComponent(x=x, y=y))
    return entity


def add_area(scene: Scene, name: str, x: float, y: float, **kwargs):
    entity = add_entity(scene, name, x, y)
    entity.add_component(ColliderComponent(width=4.0, height=4.0, **kwargs.pop("collider", {})))
    entity.add_component(AreaComponent(**kwargs))
    return entity


def add_body(scene: Scene, name: str, x: float, y: float, **kwargs):
    entity = add_entity(scene, name, x, y)
    entity.add_component(ColliderComponent(width=1.0, height=1.0, **kwargs))
    return entity


def test_area_validates_finite_values_and_round_trips() -> None:
    area = AreaComponent(
        priority=4,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=9.8,
        gravity_direction=(0.0, -1.0),
        gravity_point=True,
        gravity_point_center=(1.0, 2.0),
        gravity_point_unit_distance=2.0,
        linear_damp_mode=SpaceOverride.REPLACE,
        linear_damp=0.5,
        angular_damp_mode=SpaceOverride.COMBINE_REPLACE,
        angular_damp=0.25,
        enabled=False,
    )

    assert component_from_dict(area.to_dict()).to_dict() == area.to_dict()
    assert component_type_spec("area").cls is AreaComponent
    with pytest.raises(ValueError):
        AreaComponent(gravity=math.inf)
    with pytest.raises(ValueError):
        AreaComponent(gravity_direction=(0.0,))
    with pytest.raises(ValueError):
        AreaComponent(linear_damp=-1.0)


def test_scene_round_trip_and_missing_collider_keep_area_data_without_activation() -> None:
    scene = Scene("areas")
    entity = add_entity(scene, "area-without-volume", 0.0, 0.0)
    area = AreaComponent(gravity_mode=SpaceOverride.REPLACE, gravity=3.0)
    entity.add_component(area)

    loaded = Scene.from_dict(scene.to_dict())
    loaded_entity = loaded.find_entity(entity.entity_id)
    assert loaded_entity is not None
    assert loaded_entity.get_component(AreaComponent).to_dict() == area.to_dict()
    assert PhysicsWorld2D(loaded).resolve_area_effect("missing") == AreaEffect2D()


def test_area_resolution_reuses_overlap_filtering_and_orders_priority() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)
    low = add_area(
        scene,
        "low",
        0.0,
        0.0,
        priority=1,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=2.0,
        linear_damp_mode=SpaceOverride.COMBINE,
        linear_damp=1.0,
        collider={"layer": 1, "mask": 2},
    )
    high = add_area(
        scene,
        "high",
        0.0,
        0.0,
        priority=10,
        gravity_mode=SpaceOverride.REPLACE_COMBINE,
        gravity=5.0,
        linear_damp_mode=SpaceOverride.COMBINE_REPLACE,
        linear_damp=3.0,
        collider={"layer": 1, "mask": 2},
    )

    result = PhysicsWorld2D(scene).resolve_area_effect(
        body.entity_id,
        gravity=(1.0, 0.0),
        linear_damp=0.5,
    )

    assert result.gravity == pytest.approx((0.0, -7.0))
    assert result.linear_damp == pytest.approx(3.5)
    assert result.angular_damp == 0.0
    assert result.area_ids == (high.entity_id, low.entity_id)


def test_area_volume_does_not_need_to_be_solid_or_a_trigger() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)
    add_area(
        scene,
        "nonsolid-area",
        0.0,
        0.0,
        gravity_mode=SpaceOverride.REPLACE,
        gravity=4.0,
        collider={"layer": 1, "mask": 2, "solid": False, "trigger": False},
    )

    result = PhysicsWorld2D(scene).resolve_area_effect(body.entity_id)

    assert result.gravity == pytest.approx((0.0, -4.0))


def test_area_modes_stop_only_their_field_and_disabled_inputs_are_ignored() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)
    add_area(
        scene,
        "replace",
        0.0,
        0.0,
        priority=5,
        gravity_mode=SpaceOverride.REPLACE,
        gravity=7.0,
        linear_damp_mode=SpaceOverride.REPLACE_COMBINE,
        linear_damp=4.0,
        angular_damp_mode=SpaceOverride.COMBINE,
        angular_damp=2.0,
        collider={"layer": 1, "mask": 2},
    )
    add_area(
        scene,
        "lower",
        0.0,
        0.0,
        priority=1,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=100.0,
        linear_damp_mode=SpaceOverride.COMBINE,
        linear_damp=1.0,
        angular_damp_mode=SpaceOverride.COMBINE,
        angular_damp=3.0,
        collider={"layer": 1, "mask": 2},
    )
    disabled = add_area(
        scene,
        "disabled",
        0.0,
        0.0,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=1000.0,
        collider={"layer": 1, "mask": 2},
    )
    disabled.get_component(AreaComponent).enabled = False

    result = PhysicsWorld2D(scene).resolve_area_effect(body.entity_id)

    assert result.gravity == pytest.approx((0.0, -7.0))
    assert result.linear_damp == pytest.approx(5.0)
    assert result.angular_damp == pytest.approx(5.0)
    assert disabled.entity_id not in result.area_ids


def test_disabled_field_mode_does_not_block_lower_priority_field() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)
    add_area(
        scene,
        "default-area",
        0.0,
        0.0,
        priority=5,
        collider={"layer": 1, "mask": 2},
    )
    add_area(
        scene,
        "gravity-area",
        0.0,
        0.0,
        priority=1,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=3.0,
        collider={"layer": 1, "mask": 2},
    )

    result = PhysicsWorld2D(scene).resolve_area_effect(body.entity_id)

    assert result.gravity == pytest.approx((0.0, -3.0))


def test_point_gravity_uses_local_center_and_inverse_square_scale() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 2.0, 0.0, layer=2, mask=1)
    add_area(
        scene,
        "point",
        0.0,
        0.0,
        gravity_mode=SpaceOverride.REPLACE,
        gravity=8.0,
        gravity_point=True,
        gravity_point_center=(0.0, 0.0),
        gravity_point_unit_distance=1.0,
        collider={"layer": 1, "mask": 2},
    )

    result = PhysicsWorld2D(scene).resolve_area_effect(body.entity_id)

    assert result.gravity == pytest.approx((-2.0, 0.0))


def test_equal_priority_areas_preserve_scene_order() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)
    first = add_area(
        scene,
        "first",
        0.0,
        0.0,
        priority=3,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=1.0,
        collider={"layer": 1, "mask": 2},
    )
    second = add_area(
        scene,
        "second",
        0.0,
        0.0,
        priority=3,
        gravity_mode=SpaceOverride.COMBINE,
        gravity=2.0,
        collider={"layer": 1, "mask": 2},
    )

    result = PhysicsWorld2D(scene).resolve_area_effect(body.entity_id)

    assert result.area_ids == (first.entity_id, second.entity_id)
    assert result.gravity == pytest.approx((0.0, -3.0))


def test_area_collider_remains_compatible_with_trigger_lifecycle() -> None:
    scene = Scene("areas")
    area = add_area(
        scene,
        "trigger-area",
        0.0,
        0.0,
        collider={"layer": 1, "mask": 2, "solid": False, "trigger": True},
    )
    body = add_body(scene, "body", 0.0, 0.0, layer=2, mask=1)

    assert PhysicsWorld2D(scene).step_triggers() == (
        TriggerEvent("entered", area.entity_id, body.entity_id),
    )


def test_area_effect_result_rejects_non_finite_query_inputs() -> None:
    scene = Scene("areas")
    body = add_body(scene, "body", 0.0, 0.0)
    world = PhysicsWorld2D(scene)

    with pytest.raises(ValueError):
        world.resolve_area_effect(body.entity_id, gravity=(math.nan, 0.0))
    with pytest.raises(ValueError):
        world.resolve_area_effect(body.entity_id, linear_damp=math.inf)
