"""Launch Neon Arena with the Pygame runtime and renderer."""

from __future__ import annotations

import importlib
from pathlib import Path

from expra_engine.core.engine import Engine
from expra_engine.runtime import PygameRenderer, PygameRuntime, RenderFrame

from examples.neon_arena.game import NeonArenaGame, load_scene


def main() -> None:
    pygame = importlib.import_module("pygame")
    pygame.init()
    project_dir = Path(__file__).parent
    engine = Engine()
    engine.set_scene(load_scene(project_dir / "scenes" / "main.json"))
    surface = pygame.display.set_mode((800, 600))
    runtime = PygameRuntime(
        engine,
        pygame_module=pygame,
        surface_factory=lambda size: surface,
        size=(800, 600),
    )
    game = NeonArenaGame(
        runtime,
        left_key=pygame.K_LEFT,
        right_key=pygame.K_RIGHT,
        up_key=pygame.K_UP,
        down_key=pygame.K_DOWN,
        restart_key=pygame.K_r,
    )
    renderer = PygameRenderer(
        pygame,
        surface,
        world_bounds=(0, 0, 100, 100),
        arena_bounds=(0, 0, 800, 600),
    )
    runtime.render_callback = lambda _surface, _engine: renderer.on_render(
        RenderFrame(engine.active_scene, score=game.score, status=game.status)
    )
    engine.add_system(game)
    engine.play()
    runtime.run()


if __name__ == "__main__":
    main()
