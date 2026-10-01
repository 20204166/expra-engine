"""Canonical editor document identity and dirty-state tests."""

from pathlib import Path

from expra_engine.core.document_kind import DocumentKind
from expra_engine.core.scene import Level, Scene
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.active_document import ActiveDocument


def test_active_document_tracks_typed_identity_path_selection_and_play_source() -> None:
    document = ActiveDocument()
    level = Level("Forest")
    path = Path("levels/forest.level.pb")

    document.open(level, path)

    assert document.document is level
    assert document.kind is DocumentKind.LEVEL
    assert document.path == path
    assert document.play_source is level
    assert document.selection == ()
    assert not document.is_dirty

    document.select(("tree", "tree"))
    assert document.selection == ("tree",)


def test_opening_world_replaces_scene_identity_and_resets_undo_ownership() -> None:
    document = ActiveDocument()
    scene = Scene("House")
    document.open(scene, Path("scenes/house.scene.pb"))
    document.mark_dirty()
    document.select(("window",))
    document.command_stack.mark_clean()
    world = World(
        "Main World",
        world_id="main-world",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )

    document.open(world, Path("worlds/main.world.pb"))

    assert document.document is world
    assert document.kind is DocumentKind.WORLD
    assert document.play_source is world
    assert document.selection == ()
    assert not document.is_dirty
    assert not document.command_stack.can_undo


def test_mark_saved_clears_dirty_state_only_when_called() -> None:
    """Mirrors project_workflow.py's save contract: callers call mark_saved only
    after a successful write and return early on failure without calling it, so
    a failed save leaves dirty state untouched here by simply never reaching it.
    """
    document = ActiveDocument()
    document.open(Scene("Town"), Path("levels/town.level.pb"))
    document.mark_dirty()

    assert document.is_dirty

    document.mark_saved(Path("levels/town.level.pb"))

    assert not document.is_dirty
