"""Canonical Level-local to hierarchy-composed World transform tests."""

from __future__ import annotations

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene


def test_world_transform_composes_all_parent_translation_rotation_and_scale() -> None:
    scene = Scene("World pose")
    root = scene.create_entity("Level Origin", entity_id="root")
    root.add_component(
        TransformComponent(x=100.0, y=50.0, rotation=90.0, scale_x=2.0, scale_y=3.0)
    )
    parent = scene.create_entity("Parent", entity_id="parent", parent_id="root")
    parent.add_component(TransformComponent(x=1.0, y=2.0, scale_x=2.0, scale_y=2.0))
    child = scene.create_entity("Child", entity_id="child", parent_id="parent")
    child.add_component(TransformComponent(x=3.0, y=4.0))

    pose = scene.world_transform("child")

    assert pose.position == pytest.approx((70.0, 64.0))
    assert pose.rotation == pytest.approx(90.0)
    assert pose.scale == pytest.approx((4.0, 6.0))
    assert scene.world_pose("child") == pytest.approx((70.0, 64.0, 90.0))
    assert (child.get_component(TransformComponent).x, child.get_component(TransformComponent).y) == (
        3.0,
        4.0,
    )


def test_scene_entity_transfer_moves_one_owned_graph_and_instance_bookkeeping() -> None:
    source = Scene("Level runtime")
    root = source.create_entity("Instance", entity_id="root")
    child = source.create_entity("Materialized child", entity_id="child", parent_id="root")
    source._set_instance_children(root.entity_id, {child.entity_id})
    target = Scene("World aggregate")

    moved = source.transfer_entities_to(target)

    assert moved == (root, child)
    assert source.entities == ()
    assert target.entities == (root, child)
    assert not source.is_instance_materialized("child")
    assert target.is_instance_materialized("child")
    assert target.find_entity("child") is child
