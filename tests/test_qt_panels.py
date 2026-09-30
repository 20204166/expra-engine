"""Qt panel behaviour: hierarchy, asset browser and inspector.

Covers row reconciliation call counts, retained state, selection, control reuse and
callbacks against the real Qt panels (offscreen).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from expra_engine.core.component import TransformComponent
from expra_engine.core.scene import Scene, SceneInstanceComponent
from expra_engine.core.world import LevelDescriptor, World
from expra_engine.editor.assets import AssetEntry
from expra_engine.filesystem import ResourceId
from expra_engine.observability import ObservabilityWatcher
from expra_engine.runtime.collider import ColliderComponent
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.script_component import ScriptComponent
from tests.support.qt_app import ensure_qt_app, pump_qt

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class Harness:
    """Build the Qt panels headless and expose the few widget-level probes tests need."""

    def __init__(self) -> None:
        ensure_qt_app()
        self._qt_widgets: list[Any] = []

    def close(self) -> None:
        for widget in self._qt_widgets:
            widget.close()
            widget.deleteLater()
        pump_qt(15)

    def pump(self) -> None:
        pump_qt(15)

    def _show(self, panel: Any, width: int, height: int) -> Any:
        panel.resize(width, height)
        panel.show()
        self._qt_widgets.append(panel)
        return panel

    def hierarchy(self, **callbacks: Any) -> Any:
        from expra_engine.editor.qt.hierarchy import HierarchyPanel

        panel = self._show(HierarchyPanel(**callbacks), 300, 400)
        self.pump()
        return panel

    def assets(self, root_directory: Path, **kwargs: Any) -> Any:
        from expra_engine.editor.qt.asset_browser import AssetBrowserPanel

        panel = self._show(AssetBrowserPanel(root_directory=root_directory, **kwargs), 300, 400)
        self.pump()
        return panel

    def inspector(self, **callbacks: Any) -> Any:
        from PySide6.QtTest import QTest

        from expra_engine.editor.qt.inspector import InspectorPanel

        panel = self._show(InspectorPanel(**callbacks), 360, 240)
        panel.activateWindow()
        QTest.qWaitForWindowActive(panel)
        self.pump()
        return panel

    # -- probes -----------------------------------------------------------

    def user_select(self, panel: Any, ids: tuple[str, ...]) -> None:
        """Select rows the way a user click would (fires the selection handler)."""
        panel._tree.selection_set(ids)
        self.pump()

    def content_children(self, panel: Any) -> tuple[Any, ...]:
        from PySide6.QtWidgets import QWidget

        return tuple(panel._content.findChildren(QWidget))

    def entry_text(self, widget: Any) -> str:
        return str(widget.text())

    def type_and_commit(self, widget: Any, text: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        widget.setFocus()
        widget.setText(text)
        QTest.keyClick(widget, Qt.Key.Key_Return)
        self.pump()

    def toggle(self, widget: Any) -> None:
        widget.click()
        self.pump()

    def focus(self, widget: Any) -> None:
        pump_qt(30)  # let the layout show freshly built widgets before focusing
        widget.setFocus()
        pump_qt(15)

    def has_focus(self, widget: Any) -> bool:
        from PySide6.QtWidgets import QApplication

        return QApplication.focusWidget() is widget

    def drop_focus(self, panel: Any) -> None:
        from PySide6.QtWidgets import QApplication

        focused = QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
        pump_qt(30)

    def scroll_to_fraction(self, panel: Any, fraction: float) -> None:
        pump_qt(40)  # let the scroll area lay out its (tall) content first
        bar = panel._scroll.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(int(bar.maximum() * fraction))
        pump_qt(15)

    def scroll_fraction(self, panel: Any) -> float:
        bar = panel._scroll.verticalScrollBar()
        return bar.value() / bar.maximum() if bar.maximum() else 0.0


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.close()


def _counters() -> dict[str, int]:
    return {"insert": 0, "delete": 0, "item": 0, "move": 0}


def _count_calls(tree: Any, names: dict[str, int]) -> None:
    for name in names:
        original = getattr(tree, name)

        def counted(*args: Any, _o: Any = original, _n: str = name, **kwargs: Any) -> Any:
            names[_n] += 1
            return _o(*args, **kwargs)

        setattr(tree, name, counted)


# ---------------------------------------------------------------- hierarchy


def test_hierarchy_preserves_parent_nesting(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Nested")
    parent = scene.create_entity("Parent")
    child = scene.create_entity("Child", parent_id=parent.entity_id)
    panel.render(scene)
    h.pump()
    assert panel._tree.get_children("") == (parent.entity_id,)
    assert panel._tree.get_children(parent.entity_id) == (child.entity_id,)


def test_hierarchy_render_retains_existing_items_and_selection(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Retained")
    entity = scene.create_entity("Player")
    scene.create_entity("Child", parent_id=entity.entity_id)
    panel.render(scene)
    panel._tree.item(entity.entity_id, open=True)
    panel.select(entity.entity_id)
    h.pump()
    panel.render(scene)
    h.pump()
    assert panel._tree.exists(entity.entity_id)
    assert panel._tree.selection() == (entity.entity_id,)
    assert panel._tree.item(entity.entity_id, "text") == "[PLY] Player"
    assert panel._tree.item(entity.entity_id, "open")


def test_large_selection_uses_retained_rows_without_exists_per_id(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Large selection")
    ids = tuple(scene.create_entity(f"Entity {i}").entity_id for i in range(1000))
    panel.render(scene)
    calls = 0
    original = panel._tree.exists

    def count_exists(item: str) -> bool:
        nonlocal calls
        calls += 1
        return original(item)

    panel._tree.exists = count_exists
    panel.select_many(ids)
    assert panel._tree.selection() == ids
    assert calls == 0


def test_selection_skips_a_row_removed_outside_reconciliation(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Stale row")
    entities = tuple(scene.create_entity(f"Entity {i}") for i in range(2))
    panel.render(scene)
    panel._tree.delete(entities[0].entity_id)
    panel.select_many(tuple(e.entity_id for e in entities))
    assert panel._tree.selection() == (entities[1].entity_id,)


def test_unchanged_render_does_not_update_or_move_rows(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Unchanged")
    parent = scene.create_entity("Parent")
    for i in range(20):
        scene.create_entity(f"Child {i}", parent_id=parent.entity_id)
    panel.render(scene)
    calls = {"item": 0, "move": 0}
    _count_calls(panel._tree, calls)
    panel.render(scene)
    assert calls == {"item": 0, "move": 0}


def test_rename_updates_one_row_without_moving_others(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Rename")
    entities = [scene.create_entity(f"Entity {i}") for i in range(10)]
    panel.render(scene)
    calls = {"item": 0, "move": 0}
    _count_calls(panel._tree, calls)
    entities[4].name = "Renamed"
    panel.render(scene)
    assert calls == {"item": 1, "move": 0}
    assert panel._tree.item(entities[4].entity_id, "text") == "Renamed"


def test_add_delete_reparent_and_enabled_state_reconcile_minimally(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Structural diff")
    parent_a = scene.create_entity("Parent A")
    parent_b = scene.create_entity("Parent B")
    child = scene.create_entity("Child", parent_id=parent_a.entity_id)
    panel.render(scene)
    calls = _counters()
    _count_calls(panel._tree, calls)

    added = scene.create_entity("Added")
    panel.render(scene)
    assert calls == {"insert": 1, "delete": 0, "item": 0, "move": 0}
    calls.update(_counters())

    scene.set_entity_parent(child.entity_id, parent_b.entity_id)
    panel.render(scene)
    assert calls == {"insert": 0, "delete": 0, "item": 0, "move": 1}
    assert panel._tree.parent(child.entity_id) == parent_b.entity_id
    calls.update(_counters())

    added.enabled = False
    panel.render(scene)
    assert calls == {"insert": 0, "delete": 0, "item": 1, "move": 0}
    assert panel._tree.item(added.entity_id, "tags") == ("disabled",)
    calls.update(_counters())

    scene.remove_entity(added.entity_id)
    panel.render(scene)
    assert calls == {"insert": 0, "delete": 1, "item": 0, "move": 0}
    assert not panel._tree.exists(added.entity_id)


def test_only_the_reinserted_sibling_moves(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Sibling order")
    entities = [scene.create_entity(f"Entity {i}") for i in range(3)]
    panel.render(scene)
    calls = {"move": 0}
    _count_calls(panel._tree, calls)
    scene.remove_entity(entities[0].entity_id)
    scene.add_entity(entities[0])
    panel.render(scene)
    assert panel._tree.get_children("") == (
        entities[1].entity_id,
        entities[2].entity_id,
        entities[0].entity_id,
    )
    assert calls["move"] == 1


def test_survivor_is_reparented_out_of_a_removed_subtree(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Parent deletion and reparent")
    removed = scene.create_entity("Removed Parent")
    surviving = scene.create_entity("Surviving Parent")
    child = scene.create_entity("Child", parent_id=removed.entity_id)
    panel.render(scene)
    scene.set_entity_parent(child.entity_id, surviving.entity_id)
    scene.remove_entity(removed.entity_id)
    panel.render(scene)
    assert not panel._tree.exists(removed.entity_id)
    assert panel._tree.exists(child.entity_id)
    assert panel._tree.parent(child.entity_id) == surviving.entity_id


def test_render_handles_more_than_one_thousand_nested_entities(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Deep")
    parent_id = None
    for i in range(1_200):
        parent_id = scene.create_entity(f"Node {i}", parent_id=parent_id).entity_id
    panel.render(scene)
    assert len(panel._entity_ids) == 1_200
    assert panel._tree.get_children("")[0] == scene.roots()[0].entity_id


def test_role_markers_and_instance_labels(h) -> None:
    panel = h.hierarchy()
    scene = Scene("Roles")
    camera = scene.create_entity("Camera")
    player = scene.create_entity("Player")
    compact = scene.create_entity("Player Marker")
    room = scene.create_entity("Room Instance")
    room.add_component(SceneInstanceComponent("scenes/room.json"))
    wall = scene.create_entity("Wall", parent_id=room.entity_id)
    scene._set_instance_children(room.entity_id, {wall.entity_id})
    panel.render(scene)
    text = panel._tree.item
    assert text(camera.entity_id, "text") == "[CAM] Camera"
    assert text(player.entity_id, "text") == "[PLY] Player"
    assert text(compact.entity_id, "text") == "[PLY] Player Marker"
    assert text(room.entity_id, "text") == "[INST] Room Instance"
    assert text(wall.entity_id, "text") == "[in] Wall"
    compact.enabled = False
    panel.render(scene)
    assert text(compact.entity_id, "tags") == ("disabled",)


def test_user_selection_reports_once_and_programmatic_selection_does_not(h) -> None:
    selections: list[tuple[str, ...]] = []
    panel = h.hierarchy(on_select=lambda ids: selections.append(tuple(ids)))
    scene = Scene("Selection")
    a, b, c = (scene.create_entity(n) for n in "ABC")
    panel.render(scene)
    panel.select_many((a.entity_id,))
    h.pump()
    assert selections == []
    h.user_select(panel, (b.entity_id, c.entity_id))
    assert selections == [(b.entity_id, c.entity_id)]
    h.user_select(panel, (b.entity_id, c.entity_id))
    assert selections == [(b.entity_id, c.entity_id)]
    panel.select_many(("missing", b.entity_id, b.entity_id))
    assert panel._tree.selection() == (b.entity_id,)


def test_world_mode_swaps_buttons_rows_and_action_states(h) -> None:
    from expra_engine.coordinators.button_coordinator import ButtonCoordinator

    actions = ButtonCoordinator()
    for action_id in (
        "add_entity",
        "add_world_level",
        "create_world_connection",
        "delete_entity",
        "duplicate_selection",
    ):
        actions.register(action_id, lambda: None)
    panel = h.hierarchy(actions=actions)
    world = World(
        "Vey",
        world_id="vey",
        levels=(
            LevelDescriptor("a", "levels/a.level.pb", origin=(0.0, 0.0)),
            LevelDescriptor("b", "levels/b.level.pb", origin=(9.0, 0.0)),
        ),
        initial_level_id="a",
    )
    panel.render(world)
    h.pump()
    rows = [panel._tree.item(i, "text") for i in panel._row_state]
    assert rows == [
        "Vey",
        "Levels",
        "a — levels/a.level.pb [Initial]",
        "b — levels/b.level.pb",
        "Connections",
    ]
    assert actions.is_enabled("add_world_level") is True
    assert actions.is_enabled("add_entity") is False
    assert actions.is_enabled("delete_entity") is False
    panel.render(Scene("Back"))
    assert actions.is_enabled("add_world_level") is False


# ------------------------------------------------------------ asset browser


def _entry(root: Path, rel: str, *, folder: bool = False) -> AssetEntry:
    return AssetEntry(
        root / rel,
        Path(rel).name,
        folder,
        ResourceId.parse(f"assets://{rel}"),
    )


def test_asset_browser_renders_logical_ids_and_display_names(h, tmp_path) -> None:
    panel = h.assets(tmp_path)
    panel.render_entries((_entry(tmp_path, "textures", folder=True), _entry(tmp_path, "textures/hero.png")))
    row = panel._tree.get_children("")[0]
    child = panel._tree.get_children(row)[0]
    assert panel._tree.item(row, "text") == "textures"
    assert panel._tree.item(child, "text") == "hero.png"
    assert panel._tree.set(child, "logical_id") == "assets://textures/hero.png"


def test_asset_unchanged_refresh_reuses_rows_and_browser_state(h, tmp_path) -> None:
    panel = h.assets(tmp_path, coordinator=None)
    folder = _entry(tmp_path, "textures", folder=True)
    hero = _entry(tmp_path, "textures/hero.png")
    panel.render_entries((folder, hero))
    folder_id = panel._iid_for_path(folder.path)
    hero_id = panel._iid_for_path(hero.path)
    panel._tree.item(folder_id, open=True)
    panel._tree.selection_set(hero_id)
    h.pump()
    calls = _counters()
    _count_calls(panel._tree, calls)
    for _ in range(5):
        panel.render_entries((_entry(tmp_path, "textures", folder=True), _entry(tmp_path, "textures/hero.png")))
    assert calls == {"insert": 0, "delete": 0, "item": 0, "move": 0}
    assert len(panel._path_iids) == len(panel._entries) + 1
    assert panel._tree.item(folder_id, "open")
    assert panel._tree.selection() == (hero_id,)
    assert panel.selected_entry == _entry(tmp_path, "textures/hero.png")


def test_asset_small_delta_preserves_selection_and_expansion(h, tmp_path) -> None:
    panel = h.assets(tmp_path, coordinator=None)
    folder = _entry(tmp_path, "textures", folder=True)
    first = _entry(tmp_path, "textures/a.png")
    last = _entry(tmp_path, "textures/c.png")
    panel.render_entries((folder, first, last))
    folder_id = panel._iid_for_path(folder.path)
    first_id = panel._iid_for_path(first.path)
    panel._tree.item(folder_id, open=True)
    panel._tree.selection_set(first_id)
    h.pump()
    calls = _counters()
    _count_calls(panel._tree, calls)
    added = _entry(tmp_path, "textures/b.png")
    refreshed_first = _entry(tmp_path, "textures/a.png")
    panel.render_entries((folder, refreshed_first, added, _entry(tmp_path, "textures/c.png")))
    assert calls == {"insert": 1, "delete": 0, "item": 0, "move": 0}
    assert panel._tree.get_children(folder_id) == tuple(
        panel._iid_for_path(p.path) for p in (first, added, last)
    )
    assert panel._tree.selection() == (first_id,)
    assert panel._tree.item(folder_id, "open")
    assert panel.selected_entry is refreshed_first


def test_asset_removal_clears_selection_and_folder_classification_updates(h, tmp_path) -> None:
    panel = h.assets(tmp_path, coordinator=None)
    node = _entry(tmp_path, "node")
    panel.render_entries((node,))
    node_id = panel._iid_for_path(node.path)
    panel._tree.selection_set(node_id)
    h.pump()
    folder = _entry(tmp_path, "node", folder=True)
    panel.render_entries((folder,))
    assert panel._tree.set(node_id, "kind") == "Folder"
    assert panel._tree.selection() == (node_id,)
    assert panel.selected_entry is folder
    panel.render_entries(())
    assert panel._tree.selection() == ()
    assert panel.selected_entry is None


def test_asset_folder_navigation_keeps_child_after_parent_branch_is_removed(h, tmp_path) -> None:
    panel = h.assets(tmp_path, coordinator=None)
    folder = _entry(tmp_path, "textures", folder=True)
    image = _entry(tmp_path, "textures/hero.png")
    panel.render_entries((folder, image))
    panel._current_directory = folder.path
    panel.render_entries((image,))
    image_id = panel._iid_for_path(image.path)
    assert panel._tree.exists(image_id)
    assert panel._tree.parent(image_id) == ""
    assert panel._tree.get_children("") == (image_id,)


def test_asset_population_uses_one_stable_observability_target(h, tmp_path) -> None:
    observer = ObservabilityWatcher()
    panel = h.assets(tmp_path, coordinator=None, observer=observer)
    panel.render_entries((_entry(tmp_path, "hero.png"),))
    metrics = observer.snapshot().metrics
    assert len(metrics) == 1
    assert metrics[0].target == "ui:assets:populate"
    assert metrics[0].count == 1


def test_asset_open_folder_navigation_and_file_open_callbacks(h, tmp_path) -> None:
    (tmp_path / "textures").mkdir()
    (tmp_path / "textures" / "hero.png").write_bytes(b"png")
    opened: list[AssetEntry] = []
    panel = h.assets(tmp_path, coordinator=None, on_open=opened.append)
    panel.refresh()
    h.pump()
    folder_id = panel._iid_for_path(tmp_path / "textures")
    assert panel._tree.exists(folder_id)
    panel._tree.selection_set(folder_id)
    h.pump()
    panel._activate_selected()
    assert panel.current_directory == tmp_path / "textures"
    h.pump()
    hero_id = panel._iid_for_path(tmp_path / "textures" / "hero.png")
    panel._tree.selection_set(hero_id)
    h.pump()
    panel._activate_selected()
    assert [entry.name for entry in opened] == ["hero.png"]
    panel.navigate_up()
    assert panel.current_directory == tmp_path.resolve()


# ---------------------------------------------------------------- inspector


def test_inspector_empty_state_and_render(h) -> None:
    panel = h.inspector()
    panel.render(None)
    assert panel._current_entity_id is None
    entity = Scene("Scene").create_entity("Player")
    entity.add_component(TransformComponent())
    panel.render(entity)
    h.pump()
    assert panel._current_entity_id == entity.entity_id


def test_inspector_reuses_controls_and_updates_values_for_matching_schema(h) -> None:
    panel = h.inspector()
    scene = Scene("Inspector reuse")
    first = scene.create_entity("First")
    first.add_component(TransformComponent(x=1.0))
    second = scene.create_entity("Second")
    second.add_component(TransformComponent(x=2.0))
    panel.render(first)
    h.pump()
    name_var = panel._name_var
    variables = dict(panel._component_vars)
    children = h.content_children(panel)
    panel.render(second)
    assert panel._name_var is name_var
    assert panel._name_var.get() == "Second"
    for field, variable in variables.items():
        assert panel._component_vars[field] is variable
    assert panel._component_vars[(0, "x")].get() == "2.0"
    assert h.content_children(panel) == children
    second.get_component(TransformComponent).x = 7.0
    panel.render(second)
    assert panel._component_vars[(0, "x")].get() == "7.0"
    assert h.content_children(panel) == children


def test_reused_component_entry_commits_to_the_current_entity(h) -> None:
    changed: list[tuple[Any, ...]] = []
    panel = h.inspector(on_component_change=lambda *args: changed.append(args))
    scene = Scene("Component callbacks")
    first = scene.create_entity("First")
    first.add_component(TransformComponent())
    first.add_component(ColliderComponent(width=12.5))
    second = scene.create_entity("Second")
    second.add_component(TransformComponent())
    second.add_component(ColliderComponent(width=20.0))
    panel.render(first)
    entry = panel._component_widgets[(1, "width")]
    panel.render(second)
    assert panel._component_widgets[(1, "width")] is entry
    assert h.entry_text(entry) == "20.0"
    h.type_and_commit(entry, "37.5")
    assert changed == [(second.entity_id, "collider", "width", 37.5)]


def test_reused_script_controls_commit_to_the_current_entity(h) -> None:
    changed: list[tuple[Any, ...]] = []
    panel = h.inspector(on_script_value_change=lambda *args: changed.append(args))
    scene = Scene("Script callbacks")

    def make(name: str, speed: int) -> Any:
        entity = scene.create_entity(name)
        entity.add_component(TransformComponent())
        entity.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={"speed": speed, "enabled": False},
            )
        )
        return entity

    first, second = make("First", 2), make("Second", 8)
    panel.render(first)
    speed_entry = panel._script_widgets[(1, "speed")]
    enabled_check = panel._script_widgets[(1, "enabled")]
    panel.render(second)
    assert panel._script_widgets[(1, "speed")] is speed_entry
    assert panel._script_widgets[(1, "enabled")] is enabled_check
    assert h.entry_text(speed_entry) == "8"
    h.type_and_commit(speed_entry, "11")
    h.toggle(enabled_check)
    assert changed == [
        (second.entity_id, 1, "speed", 11),
        (second.entity_id, 1, "enabled", True),
    ]


def test_inspector_rebuilds_when_component_or_script_schema_changes(h) -> None:
    panel = h.inspector()
    entity = Scene("Schema changes").create_entity("Player")
    entity.add_component(TransformComponent())
    panel.render(entity)
    original_name_var = panel._name_var
    collider = ColliderComponent()
    entity.add_component(collider)
    panel.render(entity)
    assert panel._name_var is not original_name_var
    assert (1, "width") in panel._component_vars
    script = ScriptComponent("project://scripts/probe.py", "Probe", exposed_values={"speed": 1})
    entity.add_component(script)
    panel.render(entity)
    assert (2, "speed") in panel._script_vars
    old_speed = panel._script_vars[(2, "speed")]
    script.exposed_values["enabled"] = False
    panel.render(entity)
    assert panel._script_vars[(2, "speed")] is not old_speed
    assert (2, "enabled") in panel._script_vars
    entity.remove_component(collider)
    panel.render(entity)
    assert (1, "width") not in panel._component_vars


def test_inspector_defers_same_schema_selection_while_a_field_is_focused(h) -> None:
    panel = h.inspector()
    scene = Scene("Inspector focus")
    first = scene.create_entity("First")
    first.add_component(TransformComponent())
    second = scene.create_entity("Second")
    second.add_component(TransformComponent(x=9.0))
    changed: list[tuple[Any, ...]] = []
    panel._on_component_change = lambda *args: changed.append(args)
    panel.render(first)
    variable = panel._component_vars[(0, "x")]
    old_name_var = panel._name_var
    entry = panel._component_widgets[(0, "x")]
    h.focus(entry)
    assert h.has_focus(entry)
    variable.set("3.")
    panel.render(second)
    assert panel._name_var is old_name_var
    assert panel._current_entity_id == first.entity_id
    assert variable.get() == "3."
    assert h.has_focus(entry)
    h.drop_focus(panel)
    h.pump()
    h.pump()
    assert changed == [(first.entity_id, "transform", "x", 3.0)]
    assert panel._current_entity_id == second.entity_id
    assert panel._component_vars[(0, "x")].get() == "9.0"


def test_inspector_preserves_scroll_position_across_schema_rebuild(h) -> None:
    panel = h.inspector()

    def make(name: str, extra: dict[str, int]) -> Any:
        entity = Scene("Scroll").create_entity(name)
        entity.add_component(TransformComponent())
        entity.add_component(
            ScriptComponent(
                "project://scripts/probe.py",
                "Probe",
                exposed_values={**{f"field_{i}": i for i in range(30)}, **extra},
            )
        )
        return entity

    panel.render(make("First", {}))
    h.pump()
    h.scroll_to_fraction(panel, 0.7)
    panel.render(make("Second", {"new_field": 1}))
    h.pump()
    assert h.scroll_fraction(panel) > 0.6


def test_material_inspector_routes_normal_map_actions(h) -> None:
    calls: list[tuple[object, ...]] = []
    panel = h.inspector(
        on_normal_map_preview=lambda entity_id, index: calls.append(("preview", entity_id, index)),
        on_normal_map_auto_map=lambda: calls.append(("auto_map",)),
    )
    entity = Scene("Normal map actions").create_entity("Stone")
    entity.add_component(MaterialComponent(normal_map_mode="auto_pair"))
    panel.render(entity)
    h.pump()
    from PySide6.QtWidgets import QPushButton

    invoke = {b.text(): b.click for b in panel._content.findChildren(QPushButton)}
    invoke["Preview Normal Map"]()
    invoke["Auto-map this Level…"]()
    assert calls == [("preview", entity.entity_id, 0), ("auto_map",)]


def test_inspector_add_component_menu_lists_only_missing_components(h) -> None:
    added: list[str] = []
    panel = h.inspector(on_add_component=added.append)
    entity = Scene("Add").create_entity("Thing")
    entity.add_component(TransformComponent())
    panel.render(entity)
    h.pump()
    from PySide6.QtWidgets import QToolButton

    button = next(
        b for b in panel._content.findChildren(QToolButton) if b.text() == "+ Add Component"
    )
    labels = [a.text() for a in button.menu().actions()]
    assert "Transform" not in labels
    assert labels
    next(a for a in button.menu().actions() if a.text() == labels[0]).trigger()
    assert added


def test_world_inspector_values_placement_and_error_path(h) -> None:
    placed: list[tuple[str, tuple[float, float]]] = []
    removed: list[str] = []
    initial: list[str] = []
    panel = h.inspector(
        on_world_level_placement=lambda level_id, origin: placed.append((level_id, origin)),
        on_world_set_initial_level=initial.append,
        on_world_remove_item=removed.append,
    )
    world = World(
        "Vey",
        world_id="vey",
        levels=(
            LevelDescriptor("a", "levels/a.level.pb", origin=(0.0, 0.0)),
            LevelDescriptor("b", "levels/b.level.pb", origin=(9.0, 0.0)),
        ),
        initial_level_id="a",
    )
    panel.render_world(world, "level:b")
    h.pump()
    assert panel._world_selected_level_id == "b"
    assert panel._world_origin_x_var.get() == "9.0"
    panel._world_origin_x_var.set("12")
    panel._world_origin_y_var.set("-3.5")
    panel._apply_world_placement()
    assert placed == [("b", (12.0, -3.5))]
    values = panel._world_inspection_values(world, None)
    assert dict(values)["Levels"] == "2"
    panel.render(None)
    assert panel._world_render_key is None


def test_world_hierarchy_add_level_action_and_header(h) -> None:
    requested: list[bool] = []
    panel = h.hierarchy(on_add_level=lambda: requested.append(True))
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    panel.render(world)
    h.pump()
    assert panel._tree.exists("level:town")
    assert panel._header_label.text() == "WORLD"
    assert panel._world_add_button.isEnabled()
    assert not panel._add_button.isVisible()
    panel._world_add_button.click()
    assert requested == [True]


def test_inspector_switches_between_world_metadata_and_entity_schema(h) -> None:
    panel = h.inspector()
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb"),
        ),
        initial_level_id="town",
    )
    panel.render_world(world, "level:town")
    h.pump()
    assert panel._header_label.text() == "WORLD INSPECTOR"
    panel.render(None)
    assert panel._header_label.text() == "INSPECTOR"


def test_world_inspector_can_set_selected_level_as_initial(h) -> None:
    from PySide6.QtWidgets import QPushButton

    selected: list[str] = []
    panel = h.inspector(on_world_set_initial_level=selected.append)
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb"),
        ),
        initial_level_id="town",
    )
    panel.render_world(world, "level:forest")
    h.pump()
    button = next(b for b in panel._content.findChildren(QPushButton) if b.text() == "Set Initial Level")
    button.click()
    assert selected == ["forest"]
