"""World Hierarchy exposes descriptors and connections without Level entities."""

from expra_engine.core.world import LevelDescriptor, World, WorldConnection
from expra_engine.editor.hierarchy_rows import collect_world_rows
from expra_engine.editor.inspector_core import InspectorCore


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

    rows = collect_world_rows(world)

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

    values = InspectorCore._world_inspection_values(world, "level:town")
    connection_values = InspectorCore._world_inspection_values(world, "connection:gate")

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

    values = InspectorCore._world_inspection_values(world, None)

    assert ("Initial Level", "town") in values
    assert ("Initial entrance", "west") in values
    assert ("Primary anchor", "player") in values
