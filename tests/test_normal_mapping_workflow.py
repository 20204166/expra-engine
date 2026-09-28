from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.normal_mapping_workflow import (
    AutoMapState,
    apply_level_auto_map,
    build_level_auto_map_plan,
)
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent


def _entity_with_sprite(scene: Scene, name: str, asset: str):
    entity = scene.create_entity(name)
    entity.add_component(SpriteComponent(asset))
    return entity


def test_level_auto_map_plan_is_exact_and_does_not_mutate_scene(tmp_path: Path) -> None:
    project = Project.create("Auto Map", tmp_path / "project")
    (project.assets_dir / "tiles").mkdir(parents=True)
    (project.assets_dir / "tiles" / "stone.png").write_bytes(b"base")
    (project.assets_dir / "tiles" / "stone_normal.png").write_bytes(b"normal")
    (project.assets_dir / "tiles" / "missing.png").write_bytes(b"base without pair")
    scene = Scene("Level")
    paired = _entity_with_sprite(scene, "paired", "assets://tiles/stone.png")
    missing = _entity_with_sprite(scene, "missing", "assets://tiles/missing.png")
    unsupported = scene.create_entity("primitive")
    unsupported.add_component(PrimitiveComponent())
    explicit = _entity_with_sprite(scene, "explicit", "assets://tiles/stone.png")
    explicit.add_component(
        MaterialComponent(
            normal_map_mode="explicit", normal_texture_id="assets://tiles/stone_normal.png"
        )
    )

    plan = build_level_auto_map_plan(scene, project.resource_service())

    assert plan.assign_entity_ids == (paired.entity_id,)
    assert any(item.entity_id == paired.entity_id and item.state is AutoMapState.RESOLVED for item in plan.findings)
    assert any(item.entity_id == missing.entity_id and item.state is AutoMapState.MISSING for item in plan.findings)
    assert any(item.entity_id == unsupported.entity_id and item.state is AutoMapState.UNSUPPORTED for item in plan.findings)
    assert any(item.entity_id == explicit.entity_id and item.state is AutoMapState.PRESERVED for item in plan.findings)
    assert paired.get_component(MaterialComponent) is None


def test_apply_auto_map_is_one_undoable_idempotent_level_operation(tmp_path: Path) -> None:
    project = Project.create("Auto Map", tmp_path / "project")
    (project.assets_dir / "stone.png").write_bytes(b"base")
    (project.assets_dir / "stone_normal.png").write_bytes(b"normal")
    scene = Scene("Level")
    entity = _entity_with_sprite(scene, "stone", "assets://stone.png")
    active_document = ActiveDocument()
    active_document.open(scene)
    window = SimpleNamespace(
        _active_document=active_document,
        _update_undo_redo_state=MagicMock(),
        _present_all=MagicMock(),
    )
    plan = build_level_auto_map_plan(scene, project.resource_service())

    assert apply_level_auto_map(window, plan) is True
    material = entity.get_component(MaterialComponent)
    assert material is not None and material.normal_map_mode == "auto_pair"
    assert len(active_document.command_stack.history) == 1

    active_document.command_stack.undo()
    assert entity.get_component(MaterialComponent) is None
    active_document.command_stack.redo()
    assert entity.get_component(MaterialComponent) is not None
    assert apply_level_auto_map(window, plan) is False
    assert len(active_document.command_stack.history) == 1


def test_auto_map_rejects_a_stale_plan_for_another_active_document(tmp_path: Path) -> None:
    project = Project.create("Auto Map", tmp_path / "project")
    (project.assets_dir / "stone.png").write_bytes(b"base")
    (project.assets_dir / "stone_normal.png").write_bytes(b"normal")
    authored = Scene("Authored")
    _entity_with_sprite(authored, "stone", "assets://stone.png")
    active_document = ActiveDocument()
    active_document.open(Scene("Replacement"))
    window = SimpleNamespace(
        _active_document=active_document,
        _update_undo_redo_state=MagicMock(),
        _present_all=MagicMock(),
    )
    plan = build_level_auto_map_plan(authored, project.resource_service())

    with pytest.raises(ValueError, match="no longer active"):
        apply_level_auto_map(window, plan)

    assert active_document.command_stack.history == ()
