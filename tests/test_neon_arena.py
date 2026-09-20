"""Behavior tests for the standalone Neon Arena sample game."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from expra_engine.core.engine import Engine
from expra_engine.runtime import PygameRuntime

from examples.neon_arena.game import NeonArenaGame, load_scene


PROJECT_DIR = Path(__file__).parents[1] / "examples" / "neon_arena"


class _FakeClock:
    def __init__(self, milliseconds: list[int]) -> None:
        self.milliseconds = iter(milliseconds)

    def tick(self, frame_rate: int) -> int:
        return next(self.milliseconds)


class _FakeDisplay:
    def set_mode(self, size: tuple[int, int]) -> object:
        return object()

    def flip(self) -> None:
        pass


class _FakePygame:
    QUIT = 1
    KEYDOWN = 2
    KEYUP = 3
    K_LEFT = 10
    K_RIGHT = 11
    K_UP = 12
    K_DOWN = 13
    K_r = 14

    def __init__(self, frames: list[list[Any]]) -> None:
        self.event = SimpleNamespace(get=lambda: frames.pop(0))
        self.display = _FakeDisplay()

    def quit(self) -> None:
        pass


def _running_game(frames: list[list[Any]], clock_ticks: list[int]) -> tuple[NeonArenaGame, Engine]:
    engine = Engine()
    engine.set_scene(load_scene(PROJECT_DIR / "scenes" / "main.json"))
    pygame = _FakePygame(frames)
    runtime = PygameRuntime(
        engine,
        pygame_module=pygame,
        clock=_FakeClock(clock_ticks),
        surface_factory=pygame.display.set_mode,
    )
    game = NeonArenaGame(
        runtime,
        left_key=pygame.K_LEFT,
        right_key=pygame.K_RIGHT,
        up_key=pygame.K_UP,
        down_key=pygame.K_DOWN,
        restart_key=pygame.K_r,
    )
    engine.add_system(game)
    engine.play()
    return game, engine


class TestNeonArena(unittest.TestCase):
    def test_keyboard_movement_is_clamped_to_arena_bounds(self) -> None:
        game, engine = _running_game(
            [
                [
                    SimpleNamespace(type=_FakePygame.KEYDOWN, key=_FakePygame.K_LEFT),
                    SimpleNamespace(type=_FakePygame.KEYDOWN, key=_FakePygame.K_UP),
                ],
                [SimpleNamespace(type=_FakePygame.QUIT)],
            ],
            [17, 17],
        )

        game.player_transform.x = 0.25
        game.player_transform.y = 0.25
        game.runtime.run()

        self.assertEqual(game.player_transform.x, 0.0)
        self.assertEqual(game.player_transform.y, 0.0)
        engine.stop()

    def test_target_collection_increments_score_and_wins(self) -> None:
        game, engine = _running_game(
            [
                [SimpleNamespace(type=_FakePygame.KEYDOWN, key=_FakePygame.K_RIGHT)],
                [SimpleNamespace(type=_FakePygame.QUIT)],
            ],
            [17, 17],
        )
        game.target_transform.x = game.player_transform.x + 0.5

        game.runtime.run()

        self.assertEqual(game.score, 1)
        self.assertEqual(game.status, "won")
        self.assertFalse(game.target.enabled)
        engine.stop()

    def test_restart_resets_runtime_scene_without_mutating_saved_scene(self) -> None:
        scene_path = PROJECT_DIR / "scenes" / "main.json"
        saved_before = json.loads(scene_path.read_text(encoding="utf-8"))
        game, engine = _running_game(
            [[SimpleNamespace(type=_FakePygame.QUIT)]],
            [17],
        )
        game.score = 1
        game.status = "won"
        game.player_transform.x = 75.0
        game.target.enabled = False

        game.restart()

        self.assertEqual(engine.active_scene.to_dict(), saved_before)
        self.assertEqual(game.score, 0)
        self.assertEqual(game.status, "")
        self.assertEqual(game.player_transform.x, saved_before["entities"][0]["components"][0]["x"])
        self.assertTrue(game.target.enabled)
        self.assertEqual(json.loads(scene_path.read_text(encoding="utf-8")), saved_before)
        engine.stop()


if __name__ == "__main__":
    unittest.main()
