"""World editor graph-edit commands have real undo/redo integration coverage."""

from __future__ import annotations

from pathlib import Path

from expra_engine.core.entity import Entity
from expra_engine.core.scene import Level
from expra_engine.core.world import (
    LevelDescriptor,
    TransitionMode,
    World,
    WorldConnection,
    WorldStreamingSettings,
)
from expra_engine.editor.commands import CommandStack
from expra_engine.editor.world_authoring import WorldAuthoringWorkflow
from expra_engine.runtime.level_anchor import LevelAnchorComponent, LevelAnchorKind


def test_world_authoring_workflow_is_a_separate_document_contributor() -> None:
    assert WorldAuthoringWorkflow.__module__ == "expra_engine.editor.world_authoring"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _two_level_world() -> World:
    return World(
        "TestWorld",
        world_id="test",
        levels=(
            LevelDescriptor("a", "levels/a.level.pb", origin=(0.0, 0.0)),
            LevelDescriptor("b", "levels/b.level.pb", origin=(100.0, 0.0)),
        ),
        initial_level_id="a",
        streaming=WorldStreamingSettings(max_concurrent_loads=1, max_loaded_levels=2),
    )


def _level_with_anchor(level_id: str, anchor_id: str, kind: LevelAnchorKind) -> Level:
    level = Level(level_id)
    entity = Entity("anchor_entity")
    entity.add_component(LevelAnchorComponent(anchor_id=anchor_id, kind=kind))
    level.add_entity(entity)
    return level


class _FakeConsole:
    def log(self, _msg: str) -> None:
        pass


class _FakeProject:
    def __init__(self) -> None:
        self.path = Path("/fake")
        self.levels_dir = self.path / "levels"
        self._levels: dict[str, Level] = {}

    def document_file(self, _relative_path: str) -> None:
        pass

    def read_document(self, relative_path: str, observer=None) -> Level:
        if relative_path in self._levels:
            return self._levels[relative_path]
        return Level(Path(relative_path).stem)

    def register_level_path(self, _relative_path: str) -> None:
        pass


class _FakeEngine:
    def __init__(self, project: _FakeProject) -> None:
        self.project = project
        self._world: World | None = None

    def set_world(self, world: World, *, project, world_resource_path=None) -> None:
        self._world = world


class _ActiveDoc:
    def __init__(self, world: World) -> None:
        self.document = world


class _FakeWindow:
    def __init__(self, world: World, project: _FakeProject | None = None) -> None:
        if project is None:
            project = _FakeProject()
        self._engine = _FakeEngine(project)
        self._engine._world = world
        self._active_document = _ActiveDoc(world)
        self._command_stack = CommandStack()
        self._console = _FakeConsole()
        self._last_save_path = None

    def _update_undo_redo_state(self) -> None:
        pass

    def _present_all(self) -> None:
        pass

    def current_world(self) -> World:
        return self._active_document.document  # type: ignore[return-value]


def _workflow(window: _FakeWindow) -> WorldAuthoringWorkflow:
    return WorldAuthoringWorkflow(window)


# ─── GAP 4 undo/redo tests ────────────────────────────────────────────────────


def test_add_level_undo_redo_cycle() -> None:
    """add_level_to_world → undo → redo preserves correct level count."""
    world = _two_level_world()
    project = _FakeProject()
    window = _FakeWindow(world, project)
    wf = _workflow(window)

    wf.add_level_to_world("levels/c.level.pb")
    assert len(window.current_world().levels) == 3

    window._command_stack.undo()
    assert len(window.current_world().levels) == 2, "undo should remove the added Level"

    window._command_stack.redo()
    assert len(window.current_world().levels) == 3, "redo should restore the added Level"
    assert any(d.instance_id == "c" for d in window.current_world().levels)


def test_remove_level_undo_redo_cycle() -> None:
    """remove_level → undo → redo preserves correct level count and initial_level_id."""
    world = _two_level_world()
    window = _FakeWindow(world)
    wf = _workflow(window)

    wf.remove_level("b")
    assert len(window.current_world().levels) == 1
    assert window.current_world().initial_level_id == "a"

    window._command_stack.undo()
    assert len(window.current_world().levels) == 2, "undo should restore the removed Level"
    assert any(d.instance_id == "b" for d in window.current_world().levels)

    window._command_stack.redo()
    assert len(window.current_world().levels) == 1, "redo should remove the Level again"


def test_update_level_placement_undo_redo_no_float_drift() -> None:
    """Repeated undo/redo of placement must not accumulate float drift."""
    world = _two_level_world()
    window = _FakeWindow(world)
    wf = _workflow(window)

    original_origin = (0.0, 0.0)
    new_origin = (42.5, -17.25)
    wf.update_level_placement("a", new_origin)

    for _ in range(5):
        window._command_stack.undo()
        descriptor = next(d for d in window.current_world().levels if d.instance_id == "a")
        assert descriptor.origin == original_origin, "undo must restore exact original origin"

        window._command_stack.redo()
        descriptor = next(d for d in window.current_world().levels if d.instance_id == "a")
        assert descriptor.origin == new_origin, "redo must restore exact new origin"


def test_add_connection_undo_redo_cycle() -> None:
    """add_connection → undo → redo correctly manages connection list."""
    world = _two_level_world()
    project = _FakeProject()
    project._levels["levels/a.level.pb"] = _level_with_anchor("a", "exit_a", LevelAnchorKind.EXIT)
    project._levels["levels/b.level.pb"] = _level_with_anchor(
        "b", "enter_b", LevelAnchorKind.ENTRANCE
    )
    window = _FakeWindow(world, project)
    wf = _workflow(window)

    connection = WorldConnection(
        "a.exit_a-b.enter_b",
        source_level_id="a",
        source_anchor_id="exit_a",
        destination_level_id="b",
        destination_anchor_id="enter_b",
        transition=TransitionMode.INSTANT,
    )
    wf.add_connection(connection)
    assert len(window.current_world().connections) == 1

    window._command_stack.undo()
    assert len(window.current_world().connections) == 0, "undo should remove the connection"

    window._command_stack.redo()
    assert len(window.current_world().connections) == 1, "redo should restore the connection"
    assert window.current_world().connections[0].connection_id == "a.exit_a-b.enter_b"


def test_remove_connection_undo_redo_cycle() -> None:
    """remove_connection → undo → redo correctly manages connection list."""
    conn = WorldConnection(
        "a-to-b",
        source_level_id="a",
        source_anchor_id="exit_a",
        destination_level_id="b",
        destination_anchor_id="enter_b",
        transition=TransitionMode.INSTANT,
    )
    from dataclasses import replace

    world = replace(_two_level_world(), connections=(conn,))
    window = _FakeWindow(world)
    wf = _workflow(window)

    wf.remove_connection("a-to-b")
    assert len(window.current_world().connections) == 0

    window._command_stack.undo()
    assert len(window.current_world().connections) == 1, "undo should restore the connection"

    window._command_stack.redo()
    assert len(window.current_world().connections) == 0, "redo should remove the connection again"


def test_set_initial_level_undo_redo_cycle() -> None:
    """set_initial_level → undo → redo preserves initial_level_id correctly."""
    world = _two_level_world()
    window = _FakeWindow(world)
    wf = _workflow(window)

    assert window.current_world().initial_level_id == "a"
    wf.set_initial_level("b")
    assert window.current_world().initial_level_id == "b"

    window._command_stack.undo()
    assert window.current_world().initial_level_id == "a", "undo should restore initial level"

    window._command_stack.redo()
    assert window.current_world().initial_level_id == "b", "redo should re-apply initial level"


def test_world_commands_do_not_corrupt_scene_command_stack() -> None:
    """World authoring uses its own command stack — a separate scene stack is unaffected."""
    world = _two_level_world()
    scene_stack = CommandStack()
    window = _FakeWindow(world)
    wf = _workflow(window)

    wf.remove_level("b")
    window._command_stack.undo()

    assert not scene_stack.can_undo, "scene command stack must not be touched by World authoring"
    assert window._command_stack.can_redo, "world command stack should have a redo entry after undo"


def test_world_dirty_state_clears_on_save() -> None:
    """Command stack is dirty after an edit and clean after mark_clean()."""
    world = _two_level_world()
    window = _FakeWindow(world)
    wf = _workflow(window)

    assert not window._command_stack.is_dirty

    wf.remove_level("b")
    assert window._command_stack.is_dirty, "stack must be dirty after an authoring edit"

    window._command_stack.mark_clean()
    assert not window._command_stack.is_dirty, "stack must be clean after mark_clean()"

    window._command_stack.undo()
    assert window._command_stack.is_dirty, "undoing past save point must mark dirty again"
