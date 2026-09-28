"""World Hierarchy exposes descriptors and connections without Level entities."""

import tkinter as tk

from expra_engine.core.world import LevelDescriptor, World, WorldConnection
from expra_engine.ui.hierarchy import HierarchyPanel
from expra_engine.ui.inspector import InspectorPanel


def test_world_hierarchy_rows_show_level_references_and_connection_semantics() -> None:
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb"),
            LevelDescriptor("forest", "levels/forest.level.pb"),
        ),
        connections=(
            WorldConnection("gate", "town", "east", "forest", "west"),
        ),
        initial_level_id="town",
    )

    rows = HierarchyPanel._collect_world_rows(world)

    assert rows == [
        ("world:root", "", "Main", ()),
        ("world:levels", "world:root", "Levels", ()),
        ("level:town", "world:levels", "town — levels/town.level.pb [Initial]", ()),
        ("level:forest", "world:levels", "forest — levels/forest.level.pb", ()),
        ("world:connections", "world:root", "Connections", ()),
        (
            "connection:gate",
            "world:connections",
            "town.east → forest.west [seamless]",
            (),
        ),
    ]


def test_world_inspector_resolves_descriptor_and_connection_without_level_entities() -> None:
    world = World(
        "Main",
        world_id="main",
        levels=(
            LevelDescriptor("town", "levels/town.level.pb", origin=(10.0, 20.0)),
            LevelDescriptor("forest", "levels/forest.level.pb"),
        ),
        connections=(WorldConnection("gate", "town", "east", "forest", "west"),),
        initial_level_id="town",
    )

    values = InspectorPanel._world_inspection_values(world, "level:town")
    connection_values = InspectorPanel._world_inspection_values(world, "connection:gate")

    assert ("Resource", "levels/town.level.pb") in values
    assert ("Origin", "(10.0, 20.0)") in values
    assert ("Initial", "yes") in values
    assert ("Route", "town.east → forest.west") in connection_values
    assert ("Transition", "seamless") in connection_values


def test_world_inspector_exposes_primary_anchor_for_startup_configuration() -> None:
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
        initial_entrance_id="west",
        primary_anchor_id="player",
    )

    values = InspectorPanel._world_inspection_values(world, None)

    assert ("Initial Level", "town") in values
    assert ("Initial entrance", "west") in values
    assert ("Primary anchor", "player") in values


def test_hierarchy_renders_world_rows_and_exposes_world_add_level_action() -> None:
    root = tk.Tk()
    root.withdraw()
    requested: list[bool] = []
    world = World(
        "Main",
        world_id="main",
        levels=(LevelDescriptor("town", "levels/town.level.pb"),),
        initial_level_id="town",
    )
    try:
        panel = HierarchyPanel(root, on_add_level=lambda: requested.append(True))
        panel.pack(fill="both", expand=True)
        panel.render(world)
        root.update()

        assert panel._tree.exists("level:town")
        assert panel._header_label.cget("text") == "WORLD"
        assert str(panel._world_add_button.cget("state")) == "normal"
        assert panel._add_button.winfo_manager() == ""
        panel._world_add_button.invoke()
        assert requested == [True]
    finally:
        root.destroy()


def test_inspector_switches_between_world_metadata_and_entity_schema() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        inspector = InspectorPanel(root)
        inspector.pack(fill="both", expand=True)
        world = World(
            "Main",
            world_id="main",
            levels=(
                LevelDescriptor("town", "levels/town.level.pb"),
                LevelDescriptor("forest", "levels/forest.level.pb"),
            ),
            initial_level_id="town",
        )
        inspector.render_world(world, "level:town")
        root.update()

        assert inspector._header_label.cget("text") == "WORLD INSPECTOR"
        assert len(inspector._content.winfo_children()) == 16

        inspector.render(None)
        assert inspector._header_label.cget("text") == "INSPECTOR"
    finally:
        root.destroy()


def test_level_descriptor_inspector_applies_world_origin_through_callback() -> None:
    root = tk.Tk()
    root.withdraw()
    changes: list[tuple[str, tuple[float, float]]] = []
    try:
        inspector = InspectorPanel(
            root,
            on_world_level_placement=lambda instance_id, origin: changes.append(
                (instance_id, origin)
            ),
        )
        inspector.pack(fill="both", expand=True)
        world = World(
            "Main",
            world_id="main",
            levels=(LevelDescriptor("town", "levels/town.level.pb", origin=(1.0, 2.0)),),
            initial_level_id="town",
        )
        inspector.render_world(world, "level:town")
        root.update()

        inspector._world_origin_x_var.set("20")
        inspector._world_origin_y_var.set("30")
        inspector._apply_world_placement()

        assert changes == [("town", (20.0, 30.0))]
    finally:
        root.destroy()


def test_world_inspector_can_set_selected_level_as_initial() -> None:
    root = tk.Tk()
    root.withdraw()
    selected: list[str] = []
    try:
        inspector = InspectorPanel(
            root,
            on_world_set_initial_level=selected.append,
        )
        inspector.pack(fill="both", expand=True)
        world = World(
            "Main",
            world_id="main",
            levels=(
                LevelDescriptor("town", "levels/town.level.pb"),
                LevelDescriptor("forest", "levels/forest.level.pb"),
            ),
            initial_level_id="town",
        )
        inspector.render_world(world, "level:forest")
        root.update()
        button = next(
            item
            for item in inspector._content.winfo_children()
            if getattr(item, "cget", lambda _name: "")("text") == "Set Initial Level"
        )

        button.invoke()

        assert selected == ["forest"]
    finally:
        root.destroy()
