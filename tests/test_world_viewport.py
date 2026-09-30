"""World authoring viewport represents descriptors without loading Levels."""

from expra_engine.core.world import LevelDescriptor, World, WorldConnection
from tests.support.qt_app import ensure_qt_app, pump_qt


def test_world_viewport_draws_level_bounds_origin_initial_and_connections() -> None:
    from expra_engine.editor.qt.viewport import ViewportPanel

    ensure_qt_app()
    viewport = ViewportPanel()
    viewport.resize(800, 600)
    viewport.show()
    try:
        world = World(
            "Main",
            world_id="main",
            levels=(
                LevelDescriptor(
                    "town",
                    "levels/town.level.pb",
                    origin=(0.0, 0.0),
                    bounds=(-50.0, -50.0, 100.0, 100.0),
                ),
                LevelDescriptor("forest", "levels/forest.level.pb", origin=(100.0, 0.0)),
            ),
            connections=(WorldConnection("gate", "town", "east", "forest", "west"),),
            initial_level_id="town",
        )

        viewport.render_world(world)
        pump_qt(20)

        assert viewport._canvas.find_withtag("world:level:town")
        assert viewport._canvas.find_withtag("world:level:forest")
        assert viewport._canvas.find_withtag("world:connection:gate")
        assert viewport._canvas.find_withtag("world:initial:town")
        retained_rows = tuple(viewport._canvas.find_withtag("world:level:town"))

        viewport.render_world(world, "level:town")
        pump_qt(20)

        assert tuple(viewport._canvas.find_withtag("world:level:town")) == retained_rows
    finally:
        viewport.close()
