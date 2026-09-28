# End-to-End Tutorial: Build a Small Expra Game

A complete walkthrough from empty project to a two-Level World with a persistent
player, lighting, HUD, and an exported build.

## 1. Create the project

```bash
expra-new SmallGame /path/to/workspace
```

This creates `project.json`, a starter scene, and `__main__.py`. Open it in the
editor (`expra-editor` → Open Project).

## 2. Create a player Scene (reusable)

File → New Scene, name it `player`. Add a `SpriteComponent` (asset =
`assets://player.png`) and a `ColliderComponent` (`shape="rectangle"`,
`width/height` matching the sprite).

## 3. Add a player Behaviour

Create `scripts/player.py`:

```python
from expra_engine.core.component import TransformComponent
from expra_engine.runtime.behaviour import Behaviour, exposed


class PlayerBehaviour(Behaviour):
    speed = exposed(160.0, min=0.0, max=500.0)

    def on_update(self, dt: float) -> None:
        t = self.require_component(TransformComponent)
        if self.input.is_held("move_left"):
            t.x -= self.speed * dt
        if self.input.is_held("move_right"):
            t.x += self.speed * dt
```

Attach it: on the player entity, Add Component → `script`, set
`script_id="project://scripts/player.py"`, `behaviour_class="PlayerBehaviour"`.

## 4. Bind input

In `project.json` (or via `Project.set_input_binding`), map semantic actions:

```
"move_left": "keyboard:left" (or "keyboard:a")
"move_right": "keyboard:right" (or "keyboard:d")
```

## 5. Create Level 1

File → New Level, name it `level_1`. Instance the player: Add Entity, Add
Component → `scene_instance`, `source_path="scenes/player.scene.pb"`. Add a
`LevelAnchorComponent` (`anchor_id="exit_1"`, `kind="exit"`) at the right edge.

Add a camera: set the Level's `default_camera_id` to a camera entity, or rely on
the scene camera.

## 6. Add lighting

- Add a `CanvasModulateComponent` entity with a dark `color`.
- Add a lamp entity with a `SpriteComponent` and a `Light2DComponent`
  (`radius=6.0`, `energy=1.2`).

## 7. Add a HUD (reusable Scene)

File → New Scene, name it `hud`. Add `TextComponent` entities (health, score).
Instance it into `level_1` via `scene_instance`.

## 8. Run Level 1

Play (toolbar `▶`) to run `level_1` in-process and verify movement, lighting,
and the HUD.

## 9. Create Level 2

File → New Level, name it `level_2`. Add an entrance `LevelAnchorComponent`
(`anchor_id="entrance_2"`, `kind="entrance"`) at the left edge.

## 10. Create a World

File → New World, name it `main`.

- Add both Levels as descriptors (World toolbar "Add Level").
- Set `level_1` as the **initial level**.

## 11. Connect the Levels

World → Create Connection: source `level_1` / `exit_1` → destination `level_2` /
`entrance_2`, `transition="seamless"` (anchor positions must align within ~0.01
units).

## 12. Mark the player persistent

On the player instance entity in `level_1`, add
`WorldPersistentActorComponent` (`persistent_id="player"`). Make it a Level root
entity.

## 13. Configure the streaming anchor

Add a `StreamingAnchorComponent` (`anchor_id="primary"`) to the player (or a
marker that follows it), and set the World's `primary_anchor_id="primary"`.

## 14. Set the World as the project entrypoint

Set `project.entrypoint` (or `start_scene`) to `worlds/main.world.pb`.

## 15. Run Project

Toolbar `▶▶` launches `__main__.py` as a child process; the game starts in
`level_1`, and walking the player through `exit_1` travels to `level_2` (the
player persists across the transition).

## 16. Save game state

For cross-Launch progress, write JSON to `UserDataStore`:

```python
from pathlib import Path
from expra_engine.filesystem import UserDataStore

store = UserDataStore(Path("user-data"))
store.write_text("save.json", '{"level": "level_2"}', namespace="game")
```

For cross-Level survival within a session, use `WorldSessionStateComponent`.

## 17. Export

```bash
python -m expra_engine.export.cli /path/to/SmallGame \
  --target linux \
  --output ./builds \
  --game-name SmallGame \
  --runtime-profile pygame
```

Run `./builds/SmallGame_linux/SmallGame.sh` (or `_debug.sh` for logging).
