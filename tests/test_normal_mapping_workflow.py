from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from expra_engine.core.project import Project
from expra_engine.core.scene import Level, Scene, SceneInstanceComponent, resolve_scene_instances
from expra_engine.editor.active_document import ActiveDocument
from expra_engine.editor.normal_mapping_workflow import (
    NormalMapClassification,
    apply_normal_map_setup,
    build_normal_map_setup_plan,
)
from expra_engine.runtime.animated_sprite_2d import (
    AnimatedSprite2DComponent,
    SpriteAnimation2D,
    SpriteFrame2D,
    SpriteFrames2D,
)
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.visual_components import PrimitiveComponent, SpriteComponent


def _sprite_entity(scene: Scene, name: str, asset: str):
    entity = scene.create_entity(name)
    entity.add_component(SpriteComponent(asset))
    return entity


def _project_with(tmp_path: Path, *rel_paths: str) -> Project:
    project = Project.create("Setup", tmp_path / "project")
    for rel in rel_paths:
        target = project.assets_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
    return project


def test_plan_deduplicates_many_entities_sharing_one_texture(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "tiles/tree.png")
    scene = Scene("Level")
    for index in range(50):
        _sprite_entity(scene, f"tree_{index}", "assets://tiles/tree.png")

    plan = build_normal_map_setup_plan(scene, project.resource_service())

    assert len(plan.candidates) == 1
    assert plan.candidates[0].used_by == 50
    assert plan.candidates[0].classification is NormalMapClassification.CAN_GENERATE


def test_plan_classifies_ready_and_missing(tmp_path: Path) -> None:
    project = _project_with(
        tmp_path,
        "tiles/stone.png",
        "tiles/stone_normal.png",
        "tiles/missing.png",
    )
    scene = Scene("Level")
    ready = _sprite_entity(scene, "ready", "assets://tiles/stone.png")
    _sprite_entity(scene, "missing", "assets://tiles/missing.png")
    primitive = scene.create_entity("primitive_entity")
    primitive.add_component(PrimitiveComponent())

    plan = build_normal_map_setup_plan(scene, project.resource_service())
    by_id = plan.candidates_by_id()

    assert by_id["assets://tiles/stone.png"].classification is NormalMapClassification.READY_EXISTING
    assert by_id["assets://tiles/stone.png"].existing_normal_id == "assets://tiles/stone_normal.png"
    assert by_id["assets://tiles/missing.png"].classification is NormalMapClassification.CAN_GENERATE
    assert ready.get_component(MaterialComponent) is None
    assert plan.not_applicable_count == 1


def test_plan_preserves_disabled_and_explicit_materials(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "tiles/stone.png", "tiles/stone_normal.png")
    scene = Scene("Level")
    disabled = _sprite_entity(scene, "disabled", "assets://tiles/stone.png")
    disabled.add_component(MaterialComponent(normal_map_mode="auto_pair", enabled=False))
    explicit = _sprite_entity(scene, "explicit", "assets://tiles/stone.png")
    explicit.add_component(
        MaterialComponent(normal_map_mode="explicit", normal_texture_id="assets://tiles/stone_normal.png")
    )
    auto = _sprite_entity(scene, "auto", "assets://tiles/stone.png")
    auto.add_component(MaterialComponent(normal_map_mode="auto_pair"))

    plan = build_normal_map_setup_plan(scene, project.resource_service())
    by_id = plan.candidates_by_id()

    assert by_id["assets://tiles/stone.png"].classification is NormalMapClassification.PRESERVED
    assert plan.ready_count == 0


def test_plan_collapses_an_animation_atlas_to_one_candidate(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "hero/hero_atlas.png")
    scene = Scene("Level")
    entity = scene.create_entity("hero")
    frames = [SpriteFrame2D("assets://hero/hero_atlas.png") for _ in range(100)]
    entity.add_component(
        AnimatedSprite2DComponent(
            SpriteFrames2D({"walk": SpriteAnimation2D(frames)})
        )
    )

    plan = build_normal_map_setup_plan(scene, project.resource_service())

    assert len(plan.candidates) == 1
    assert plan.candidates[0].used_by == 100
    assert plan.candidates[0].usages[0].visual_kind == "Animation"
    assert plan.candidates[0].usages[0].animation_name == "walk"


def test_plan_aggregates_materialized_instance_children(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "hud/panel.png")
    source = Scene("HUD", scene_id="hud")
    _sprite_entity(source, "Panel", "assets://hud/panel.png")

    level = Scene("Level")
    root = level.create_entity("HUD Instance")
    root.add_component(SceneInstanceComponent("scenes/hud.scene.pb"))
    resolve_scene_instances(level, resolve_source=lambda _path: source)

    plan = build_normal_map_setup_plan(level, project.resource_service())

    assert plan.candidates == ()
    assert len(plan.instance_sources) == 1
    assert plan.instance_sources[0].visual_count == 1
    assert plan.instance_sources[0].source_path == "scenes/hud.scene.pb"


def test_apply_setup_is_one_undoable_idempotent_operation(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "stone.png", "stone_normal.png")
    scene = Scene("Level")
    entity = _sprite_entity(scene, "stone", "assets://stone.png")
    active_document = ActiveDocument()
    active_document.open(scene)
    window = SimpleNamespace(
        _active_document=active_document,
        _update_undo_redo_state=MagicMock(),
        _present_all=MagicMock(),
    )
    plan = build_normal_map_setup_plan(scene, project.resource_service())

    assert apply_normal_map_setup(window, plan, ["assets://stone.png"]) is True
    material = entity.get_component(MaterialComponent)
    assert material is not None and material.normal_map_mode == "auto_pair"
    assert len(active_document.command_stack.history) == 1

    active_document.command_stack.undo()
    assert entity.get_component(MaterialComponent) is None
    active_document.command_stack.redo()
    assert entity.get_component(MaterialComponent) is not None
    assert apply_normal_map_setup(window, plan, ["assets://stone.png"]) is False


def test_apply_setup_rejects_a_stale_plan(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "stone.png", "stone_normal.png")
    authored = Scene("Authored")
    _sprite_entity(authored, "stone", "assets://stone.png")
    active_document = ActiveDocument()
    active_document.open(Scene("Replacement"))
    window = SimpleNamespace(
        _active_document=active_document,
        _update_undo_redo_state=MagicMock(),
        _present_all=MagicMock(),
    )
    plan = build_normal_map_setup_plan(authored, project.resource_service())

    with pytest.raises(ValueError, match="no longer active"):
        apply_normal_map_setup(window, plan, ["assets://stone.png"])


def test_level_documents_plan_and_apply_like_scenes(tmp_path: Path) -> None:
    project = _project_with(tmp_path, "stone.png", "stone_normal.png")
    level = Level("Playable Level")
    entity = _sprite_entity(level, "stone", "assets://stone.png")
    active_document = ActiveDocument()
    active_document.open(level)
    window = SimpleNamespace(
        _active_document=active_document,
        _update_undo_redo_state=MagicMock(),
        _present_all=MagicMock(),
    )

    plan = build_normal_map_setup_plan(level, project.resource_service())
    assert plan.candidates_by_id()["assets://stone.png"].classification is (
        NormalMapClassification.READY_EXISTING
    )

    assert apply_normal_map_setup(window, plan, ["assets://stone.png"]) is True
    material = entity.get_component(MaterialComponent)
    assert material is not None and material.normal_map_mode == "auto_pair"
