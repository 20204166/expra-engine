"""Project persistence and entrypoint support for World documents."""

from __future__ import annotations

from pathlib import Path

import pytest

from expra_engine.core.project import Project
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.core.world import LevelDescriptor, World


def make_world() -> World:
    return World(
        "Main World",
        world_id="main-world",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )


def test_project_saves_loads_registers_world_and_preserves_active_scene(tmp_path: Path) -> None:
    project = Project.create("World Project", tmp_path / "project")
    original_scene = project.active_scene
    scene = project.load_document("scenes/main.scene.pb")
    world = make_world()

    project.save_document(world, "worlds/main.world.pb")
    restored = project.load_document("worlds/main.world.pb")

    assert restored == world
    assert project.world_paths() == ("worlds/main.world.pb",)
    assert project.active_scene is scene
    assert scene is not original_scene

    project.set_entrypoint("worlds/main.world.pb")
    project.save()
    reopened = Project.load(project.path)
    assert reopened.entrypoint == "worlds/main.world.pb"
    assert reopened.load_document() == world


def test_project_rejects_world_saved_under_another_document_extension(tmp_path: Path) -> None:
    project = Project.create("World Project", tmp_path / "project")

    with pytest.raises(ValueError):
        project.save_document(make_world(), "scenes/wrong.scene.pb")


def test_read_document_resolves_instances_without_publishing_active_scene(tmp_path: Path) -> None:
    project = Project.create("Pure Load", tmp_path / "project")
    source = Scene("Reusable", scene_id="reusable")
    source.create_entity("Wall", entity_id="wall")
    project.save_document(source, "scenes/reusable.scene.pb")
    owner = Scene("Owner", scene_id="owner")
    owner.create_entity("Instance", entity_id="instance").add_component(
        SceneInstanceComponent("scenes/reusable.scene.pb")
    )
    project.save_document(owner, "scenes/owner.scene.pb")
    active = project.load_document("scenes/main.scene.pb")

    loaded = project.read_document("scenes/owner.scene.pb")

    assert [entity.name for entity in loaded.entities] == ["Instance", "Wall"]
    assert project.active_scene is active
