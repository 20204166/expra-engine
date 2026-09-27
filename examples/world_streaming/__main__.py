"""World Streaming example — bootstrap + standalone launcher.

Run with:
    python -m examples.world_streaming

The first run generates the protobuf project files (levels and world) in this
directory. Subsequent runs load them directly.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
_WORLD_PATH = "worlds/overworld.world.pb"


def _bootstrap() -> None:
    """Generate levels/town.level.pb, levels/cave.level.pb, worlds/overworld.world.pb."""
    from expra_engine.core.component import TransformComponent
    from expra_engine.core.project import Project
    from expra_engine.core.scene import Level, LevelMetadata
    from expra_engine.core.world import (
        LevelDescriptor,
        TransitionMode,
        World,
        WorldConnection,
        WorldStreamingSettings,
    )
    from expra_engine.filesystem import ResourceId
    from expra_engine.runtime.level_anchor import LevelAnchorComponent, LevelAnchorKind
    from expra_engine.runtime.rendering import Color
    from expra_engine.runtime.script_component import ScriptComponent
    from expra_engine.runtime.visual_components import PrimitiveComponent

    # -----------------------------------------------------------------------
    # Create a bare-minimum project.  Project.create() rejects non-empty
    # directories, so we construct the Project directly and save it.
    # -----------------------------------------------------------------------
    project = Project(
        name="World Streaming Demo",
        path=PROJECT_DIR,
        game_version="0.1.0",
        input_settings={
            "move_left": "keyboard:a",
            "move_right": "keyboard:d",
            "move_left_alt": "keyboard:left",
            "move_right_alt": "keyboard:right",
        },
    )
    (PROJECT_DIR / "levels").mkdir(exist_ok=True)
    (PROJECT_DIR / "worlds").mkdir(exist_ok=True)

    # -----------------------------------------------------------------------
    # Helper: build a level, add it to the project, return the registered path.
    # -----------------------------------------------------------------------
    def _build_level(
        name: str,
        scene_id: str,
        display_name: str,
        background_color: Color,
        gate_x: float,
        gate_anchor_id: str,
        connection_id: str,
        registered_path: str,
    ) -> Level:
        level = Level(
            name=name,
            scene_id=scene_id,
            level_metadata=LevelMetadata(display_name=display_name),
        )

        # Background fill
        bg = level.create_entity("Background", entity_id=f"{scene_id}_bg")
        bg.add_component(TransformComponent(x=0.0, y=0.0))
        bg.add_component(
            PrimitiveComponent(
                kind="rectangle",
                width=22.0,
                height=12.0,
                fill=background_color,
                layer=-10,
            )
        )

        # Gate / exit marker
        gate = level.create_entity("Gate", entity_id=f"{scene_id}_gate")
        gate.add_component(TransformComponent(x=gate_x, y=0.0))
        gate.add_component(
            PrimitiveComponent(
                kind="rectangle",
                width=1.0,
                height=3.0,
                fill=Color(1.0, 0.85, 0.1),
                layer=1,
            )
        )
        gate.add_component(
            LevelAnchorComponent(
                anchor_id=gate_anchor_id,
                kind=LevelAnchorKind.EXIT,
                size=(1.2, 3.0),
            )
        )

        # Player pawn
        player = level.create_entity("Player", entity_id=f"{scene_id}_player")
        player.add_component(TransformComponent(x=0.0, y=0.0))
        player.add_component(
            PrimitiveComponent(
                kind="rectangle",
                width=0.8,
                height=1.2,
                fill=Color(0.2, 0.5, 1.0),
                layer=5,
            )
        )
        player.add_component(
            ScriptComponent(
                script_id=ResourceId.parse("project://scripts/world_streaming_behaviour.py"),
                behaviour_class="PlayerBehaviour",
                exposed_values={
                    "connection_id": connection_id,
                    "travel_edge": abs(gate_x) - 0.2,
                },
            )
        )

        project.save_document(level, registered_path)
        project.register_level_path(registered_path)
        return level

    # -----------------------------------------------------------------------
    # Build the two levels.
    # -----------------------------------------------------------------------
    _build_level(
        name="Town",
        scene_id="town",
        display_name="The Town",
        background_color=Color(0.35, 0.65, 0.25),
        gate_x=9.0,
        gate_anchor_id="town_gate",
        connection_id="town_to_cave",
        registered_path="levels/town.level.pb",
    )

    _build_level(
        name="Cave",
        scene_id="cave",
        display_name="The Cave",
        background_color=Color(0.18, 0.14, 0.12),
        gate_x=-9.0,
        gate_anchor_id="cave_exit",
        connection_id="cave_to_town",
        registered_path="levels/cave.level.pb",
    )

    # -----------------------------------------------------------------------
    # Build the World document.
    # -----------------------------------------------------------------------
    world = World(
        name="Overworld",
        world_id="overworld",
        levels=(
            LevelDescriptor(
                instance_id="town",
                resource_path="levels/town.level.pb",
                origin=(0.0, 0.0),
                tags=("surface",),
                always_loaded=False,
                priority=1,
            ),
            LevelDescriptor(
                instance_id="cave",
                resource_path="levels/cave.level.pb",
                origin=(250.0, 0.0),
                tags=("underground",),
                always_loaded=False,
                priority=0,
            ),
        ),
        connections=(
            WorldConnection(
                connection_id="town_to_cave",
                source_level_id="town",
                source_anchor_id="town_gate",
                destination_level_id="cave",
                destination_anchor_id="cave_exit",
                bidirectional=False,
                transition=TransitionMode.FADE,
                preload_distance=12.0,
                unload_distance=48.0,
            ),
            WorldConnection(
                connection_id="cave_to_town",
                source_level_id="cave",
                source_anchor_id="cave_exit",
                destination_level_id="town",
                destination_anchor_id="town_gate",
                bidirectional=False,
                transition=TransitionMode.FADE,
                preload_distance=12.0,
                unload_distance=48.0,
            ),
        ),
        initial_level_id="town",
        streaming=WorldStreamingSettings(max_concurrent_loads=2, max_loaded_levels=4),
    )
    project.save_document(world, _WORLD_PATH)
    project.register_world_path(_WORLD_PATH)

    # World is the entry point for this project.
    project.set_entrypoint(_WORLD_PATH)
    project.save()


def main() -> None:
    world_pb = PROJECT_DIR / _WORLD_PATH
    if not world_pb.exists():
        print("world_streaming: bootstrapping project files…")
        _bootstrap()
        print("world_streaming: bootstrap complete.")

    from expra_engine.runtime.project_runner import run_project

    run_project(PROJECT_DIR)


if __name__ == "__main__":
    main()
