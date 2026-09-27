"""World authoring viewport represents descriptors without loading Levels."""

import tkinter as tk

from expra_engine.core.world import LevelDescriptor, World, WorldConnection
from expra_engine.ui.viewport import ViewportPanel


def test_world_viewport_draws_level_bounds_origin_initial_and_connections() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        viewport = ViewportPanel(root)
        viewport.pack(fill="both", expand=True)
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
        root.update()

        assert viewport._canvas.find_withtag("world:level:town")
        assert viewport._canvas.find_withtag("world:level:forest")
        assert viewport._canvas.find_withtag("world:connection:gate")
        assert viewport._canvas.find_withtag("world:initial:town")
        retained_rows = tuple(viewport._canvas.find_withtag("world:level:town"))

        viewport.render_world(world, "level:town")
        root.update()

        assert tuple(viewport._canvas.find_withtag("world:level:town")) == retained_rows
    finally:
        root.destroy()
